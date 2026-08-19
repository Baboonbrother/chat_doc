"""OOXML 封裝讀取層｜XLSX 與 DOCX 共用的 zip + XML 基礎設施與安全檢查。

AD-001 決定不使用 openpyxl / python-docx，所以這裡是唯一碰觸 zip 與 XML 的地方。
安全檢查放在這一層而不是各自的 parser，是因為「檔案能不能安全地打開」與它是試算表還是文件無關。

io: in=.xlsx/.docx 檔案路徑或 bytes; out=OoxmlPackage（part 名稱 -> 原始 bytes / 解析後 XML）
依賴: 標準函式庫 zipfile / xml.etree.ElementTree
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

from docengine.core.errors import InputError, ParseError

#: 安全上限。這些數字不是猜的：一般公文用試算表遠低於它們，而超過就代表輸入不正常。
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_PART_COUNT = 2000
MAX_COMPRESSION_RATIO = 200

#: OOXML 命名空間。放在這一層是因為 loader/styles/renderer 都要用，
#: 各自定義一份遲早會漂移。
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORDML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)
_ENTITY = re.compile(rb"<!ENTITY", re.IGNORECASE)


@dataclass
class OoxmlPackage:
    """一個已載入且通過安全檢查的 OOXML 封裝。

    ``parts`` 保留每個 part 的**原始 bytes**。renderer 需要它來把我們沒有建模的 part 原封不動
    帶過去；沒有它的話，「未建模」就會變成「render 之後就消失」。
    """

    path: str | None
    sha256: str
    parts: dict[str, bytes] = field(default_factory=dict)
    part_order: list[str] = field(default_factory=list)

    def has(self, name: str) -> bool:
        return name in self.parts

    def read(self, name: str) -> bytes:
        try:
            return self.parts[name]
        except KeyError as exc:
            raise ParseError("封裝裡缺少必要的 part", part=name, path=self.path) from exc

    def xml(self, name: str) -> ET.Element:
        return parse_xml(self.read(name), part=name)

    def xml_or_none(self, name: str) -> ET.Element | None:
        return self.xml(name) if self.has(name) else None

    def iter_parts(self) -> Iterator[tuple[str, bytes]]:
        for name in self.part_order:
            yield name, self.parts[name]


def parse_xml(data: bytes, part: str = "?") -> ET.Element:
    """解析一段 XML，並先擋掉 DTD/實體。

    ElementTree 預設不解析外部實體，但 DTD 內部實體展開（billion laughs）仍可能吃光記憶體。
    正常的 OOXML part 不含 DOCTYPE，所以直接拒絕，而不是想辦法安全地處理它。
    """
    if _DOCTYPE.search(data) or _ENTITY.search(data):
        raise InputError("OOXML part 含有 DTD 或實體宣告，拒絕解析", part=part)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError("XML 解析失敗", part=part, detail=str(exc)) from exc


def load_package(path: str | Path) -> OoxmlPackage:
    """載入 OOXML 封裝並做安全檢查。"""
    p = Path(path)
    if not p.exists():
        raise InputError("檔案不存在", path=str(p))
    if not p.is_file():
        raise InputError("路徑不是檔案", path=str(p))

    size = p.stat().st_size
    if size == 0:
        raise InputError("檔案是空的", path=str(p))
    if size > MAX_PACKAGE_BYTES:
        raise InputError("檔案超過安全上限", path=str(p), size=size, limit=MAX_PACKAGE_BYTES)

    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    if not zipfile.is_zipfile(p):
        raise InputError("不是有效的 OOXML 封裝（不是 zip）", path=str(p))

    pkg = OoxmlPackage(path=str(p), sha256=digest)
    with zipfile.ZipFile(p) as z:
        infos = z.infolist()
        if len(infos) > MAX_PART_COUNT:
            raise InputError("封裝內的 part 數量超過安全上限", path=str(p), count=len(infos), limit=MAX_PART_COUNT)

        total_uncompressed = sum(i.file_size for i in infos)
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise InputError(
                "解壓後大小超過安全上限（疑似 zip bomb）",
                path=str(p),
                uncompressed=total_uncompressed,
                limit=MAX_UNCOMPRESSED_BYTES,
            )
        if size > 0 and total_uncompressed / size > MAX_COMPRESSION_RATIO:
            raise InputError(
                "壓縮比異常（疑似 zip bomb）",
                path=str(p),
                ratio=round(total_uncompressed / size, 1),
                limit=MAX_COMPRESSION_RATIO,
            )

        for info in infos:
            name = info.filename
            if name.endswith("/"):
                continue
            _assert_safe_part_name(name, str(p))
            pkg.parts[name] = z.read(info)
            pkg.part_order.append(name)

    if not pkg.parts:
        raise InputError("封裝內沒有任何 part", path=str(p))
    if "[Content_Types].xml" not in pkg.parts:
        raise InputError("封裝缺少 [Content_Types].xml，不是合法的 OOXML", path=str(p))
    return pkg


def _assert_safe_part_name(name: str, path: str) -> None:
    """擋下路徑穿越。

    zip 內的名稱可以是 ``../../etc/passwd``。我們自己不解壓到磁碟，但 part 名稱會被拿去組
    關聯路徑，所以在入口就擋掉，比在每個使用點各自防守可靠。
    """
    if name.startswith("/") or name.startswith("\\"):
        raise InputError("封裝內含絕對路徑的 part", path=path, part=name)
    if ".." in Path(name).parts:
        raise InputError("封裝內含路徑穿越的 part", path=path, part=name)
    if "\x00" in name:
        raise InputError("封裝內的 part 名稱含空位元組", path=path, part=name)


def serialize_element(element: ET.Element, default_namespace: str | None = None) -> str:
    """把元素序列化成**自足**的確定性字串，供「逐字保留」使用。

    兩個要求：

    1. 清掉 ``tail``。tail 裝的是原檔的縮排空白，保留它會讓同樣的內容因為來源檔排版不同
       而序列化成不同字串，round-trip diff 就會為了空白而假紅。
    2. 片段必須自己帶著用到的所有 xmlns 宣告。ElementTree 本來就會這樣做
       （產生 ``ns0:``/``ns1:`` 前綴與對應宣告），**絕對不可以事後把宣告清掉**——
       真實 Excel 檔的 workbook.xml 用到 mc / x15 / x15ac 等多個命名空間，
       清掉宣告只留前綴會讓輸出變成 unbound prefix 的無效 XML。
       （這正是實測 40 份真實 Excel 檔時，34 份重建後解析失敗的原因。）
    """

    def clone(src: ET.Element) -> ET.Element:
        dst = ET.Element(src.tag, dict(src.attrib))
        dst.text = src.text
        for kid in src:
            dst.append(clone(kid))
        dst.tail = None
        return dst

    copy = clone(element)
    if default_namespace:
        try:
            # 讓主命名空間的元素不帶前綴，輸出比較接近真實 Excel 檔的樣子。
            return ET.tostring(copy, encoding="unicode", default_namespace=default_namespace)
        except ValueError:
            # 該命名空間下有屬性時 ElementTree 會拒絕（屬性不能用預設命名空間）。
            # 退回帶前綴的形式：比較醜，但一樣自足且正確。
            pass
    return ET.tostring(copy, encoding="unicode")


def qn(namespace: str, tag: str) -> str:
    """組出 ElementTree 的完整標籤名 ``{ns}tag``。"""
    return f"{{{namespace}}}{tag}"


def local_name(tag: str) -> str:
    """去掉命名空間，回傳元素的本地名稱。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


__all__ = [
    "MAIN_NS",
    "REL_NS",
    "PKG_REL_NS",
    "WORDML_NS",
    "MAX_PACKAGE_BYTES",
    "MAX_UNCOMPRESSED_BYTES",
    "MAX_PART_COUNT",
    "MAX_COMPRESSION_RATIO",
    "OoxmlPackage",
    "load_package",
    "parse_xml",
    "serialize_element",
    "qn",
    "local_name",
]
