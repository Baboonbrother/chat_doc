"""XLSX golden fixture 產生器｜寫出 ODF 試算表 (.ods)，再交給 LibreOffice 轉成 .xlsx。

為什麼繞這一圈：round-trip 測試若拿我們自己 renderer 寫出來的檔案當輸入，就只證明
「我們的 renderer 和我們的 parser 互相自洽」，證明不了 parser 讀得懂真正的 Excel。
所以 fixture 必須由一個獨立的第三方寫出來——這裡是 LibreOffice 的 XLSX 匯出器（AD-002）。

fixture 刻意涵蓋 ACCEPTANCE_AND_EVIDENCE.md §2 列的難點：多工作表、隱藏工作表、
橫向與縱向合併、公式與跨表參照、數值/日期格式、列高欄寬、隱藏列欄、凍結窗格、
多種框線、以及筆數會變動的重複列區。

io: in=無; out=fixtures/xlsx/duty_roster_sample_{1,2,3}.xlsx
依賴: LibreOffice (soffice) 必須在 PATH 上
用法: python3 tools/make_fixtures/build_xlsx_fixture.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "fixtures" / "xlsx"

NS = """xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" \
xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" \
xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" \
xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" \
xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" \
xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" \
xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" \
xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0" \
xmlns:calcext="urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0\""""

STYLES = """
  <office:automatic-styles>
    <number:date-style style:name="N_DATE">
      <number:year number:style="long"/><number:text>-</number:text>
      <number:month number:style="long"/><number:text>-</number:text>
      <number:day number:style="long"/>
    </number:date-style>
    <number:number-style style:name="N_INT"><number:number number:decimal-places="0" number:min-integer-digits="1"/></number:number-style>
    <number:number-style style:name="N_DEC2"><number:number number:decimal-places="2" number:min-integer-digits="1"/></number:number-style>
    <number:percentage-style style:name="N_PCT"><number:number number:decimal-places="1" number:min-integer-digits="1"/><number:text>%</number:text></number:percentage-style>

    <style:style style:name="co_wide" style:family="table-column">
      <style:table-column-properties fo:break-before="auto" style:column-width="1.4in"/>
    </style:style>
    <style:style style:name="co_narrow" style:family="table-column">
      <style:table-column-properties fo:break-before="auto" style:column-width="0.5in"/>
    </style:style>
    <style:style style:name="co_default" style:family="table-column">
      <style:table-column-properties fo:break-before="auto" style:column-width="0.889in"/>
    </style:style>

    <style:style style:name="ro_tall" style:family="table-row">
      <style:table-row-properties style:row-height="0.45in" style:use-optimal-row-height="false"/>
    </style:style>
    <style:style style:name="ro_default" style:family="table-row">
      <style:table-row-properties style:row-height="0.178in" style:use-optimal-row-height="true"/>
    </style:style>

    <style:style style:name="ta_visible" style:family="table"><style:table-properties table:display="true"/></style:style>
    <style:style style:name="ta_hidden" style:family="table"><style:table-properties table:display="false"/></style:style>

    <style:style style:name="ce_title" style:family="table-cell">
      <style:table-cell-properties fo:background-color="#dbe5f1" style:vertical-align="middle"
        fo:border="0.06in solid #1f3864"/>
      <style:paragraph-properties fo:text-align="center"/>
      <style:text-properties fo:font-size="16pt" fo:font-weight="bold" style:font-name="Noto Sans CJK TC"/>
    </style:style>
    <style:style style:name="ce_header" style:family="table-cell">
      <style:table-cell-properties fo:background-color="#f2f2f2"
        fo:border-bottom="0.03in solid #000000" fo:border-top="0.01in solid #808080"
        fo:border-left="0.01in solid #808080" fo:border-right="0.01in solid #808080"/>
      <style:paragraph-properties fo:text-align="center"/>
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="ce_label" style:family="table-cell">
      <style:table-cell-properties fo:border-left="0.01in dashed #ff0000"/>
      <style:text-properties fo:font-style="italic"/>
    </style:style>
    <style:style style:name="ce_plain" style:family="table-cell">
      <style:table-cell-properties fo:border="0.01in solid #999999"/>
    </style:style>
    <style:style style:name="ce_date" style:family="table-cell" style:data-style-name="N_DATE">
      <style:table-cell-properties fo:border="0.01in solid #999999"/>
    </style:style>
    <style:style style:name="ce_int" style:family="table-cell" style:data-style-name="N_INT">
      <style:table-cell-properties fo:border="0.01in solid #999999"/>
      <style:paragraph-properties fo:text-align="end"/>
    </style:style>
    <style:style style:name="ce_dec2" style:family="table-cell" style:data-style-name="N_DEC2">
      <style:table-cell-properties fo:border="0.01in solid #999999"/>
    </style:style>
    <style:style style:name="ce_pct" style:family="table-cell" style:data-style-name="N_PCT">
      <style:table-cell-properties fo:border="0.01in solid #999999"/>
    </style:style>
    <style:style style:name="ce_merge_v" style:family="table-cell">
      <style:table-cell-properties fo:background-color="#fff2cc" style:vertical-align="middle"
        fo:border="0.01in solid #bf8f00"/>
      <style:paragraph-properties fo:text-align="center"/>
    </style:style>
  </office:automatic-styles>
"""

# 凍結窗格：ODF 放在 view settings 裡。LibreOffice 匯出 XLSX 時會轉成 <pane>。
SETTINGS = """
  <office:settings>
    <config:config-item-set config:name="ooo:view-settings">
      <config:config-item-map-indexed config:name="Views">
        <config:config-item-map-entry>
          <config:config-item config:name="ViewId" config:type="string">view1</config:config-item>
          <config:config-item-map-named config:name="Tables">
            <config:config-item-map-entry config:name="勤務表">
              <config:config-item config:name="HorizontalSplitMode" config:type="short">2</config:config-item>
              <config:config-item config:name="VerticalSplitMode" config:type="short">2</config:config-item>
              <config:config-item config:name="HorizontalSplitPosition" config:type="int">1</config:config-item>
              <config:config-item config:name="VerticalSplitPosition" config:type="int">4</config:config-item>
              <config:config-item config:name="PositionRight" config:type="int">1</config:config-item>
              <config:config-item config:name="PositionBottom" config:type="int">4</config:config-item>
            </config:config-item-map-entry>
          </config:config-item-map-named>
        </config:config-item-map-entry>
      </config:config-item-map-indexed>
    </config:config-item-set>
  </office:settings>
"""


def _attr(name: str) -> str:
    """把 Python 關鍵字參數名轉回 ODF 屬性名：``table__number_columns_spanned``
    -> ``table:number-columns-spanned``。前綴用雙底線分隔，其餘底線是連字號。"""
    prefix, _, rest = name.partition("__")
    return f"{prefix}:{rest.replace('_', '-')}"


def _text_cell(value: str, style: str = "ce_plain", **attrs: str) -> str:
    extra = "".join(f' {_attr(k)}="{v}"' for k, v in attrs.items())
    return (
        f'<table:table-cell table:style-name="{style}" office:value-type="string" '
        f'calcext:value-type="string"{extra}><text:p>{value}</text:p></table:table-cell>'
    )


def _num_cell(value: float, style: str = "ce_int", **attrs: str) -> str:
    extra = "".join(f' {_attr(k)}="{v}"' for k, v in attrs.items())
    return (
        f'<table:table-cell table:style-name="{style}" office:value-type="float" '
        f'office:value="{value}" calcext:value-type="float"{extra}><text:p>{value}</text:p></table:table-cell>'
    )


def _date_cell(iso: str, style: str = "ce_date") -> str:
    return (
        f'<table:table-cell table:style-name="{style}" office:value-type="date" '
        f'office:date-value="{iso}" calcext:value-type="date"><text:p>{iso}</text:p></table:table-cell>'
    )


def _formula_cell(formula: str, cached: float, style: str = "ce_int") -> str:
    return (
        f'<table:table-cell table:style-name="{style}" table:formula="{formula}" '
        f'office:value-type="float" office:value="{cached}" calcext:value-type="float">'
        f"<text:p>{cached}</text:p></table:table-cell>"
    )


def _empty(n: int = 1) -> str:
    rep = f' table:number-columns-repeated="{n}"' if n > 1 else ""
    return f"<table:table-cell{rep}/>"


def _covered(n: int = 1) -> str:
    rep = f' table:number-columns-repeated="{n}"' if n > 1 else ""
    return f"<table:covered-table-cell{rep}/>"


def build_fods(sample_no: int, staff: list[tuple[str, str, int, float]], report_date: str) -> str:
    """組出一份 .fods。三份樣本共用版面，只有值與人員筆數不同。"""
    rows: list[str] = []

    # 第 1 列：標題，橫向合併 A1:D1
    rows.append(
        '<table:table-row table:style-name="ro_tall">'
        + _text_cell(
            f"臺北市政府警察局　勤務分配表（第 {sample_no} 版）",
            "ce_title",
            table__number_columns_spanned="4",
            table__number_rows_spanned="1",
        )
        + _covered(3)
        + "</table:table-row>"
    )

    # 第 2 列：報表日期 + 隱藏欄 D 裡的內部註記
    rows.append(
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("報表日期", "ce_label")
        + _date_cell(report_date)
        + _empty()
        + _text_cell(f"internal-{sample_no}", "ce_plain")
        + "</table:table-row>"
    )

    # 第 3 列：隱藏列（內部備註，不該出現在列印版但必須被解析到）
    rows.append(
        '<table:table-row table:style-name="ro_default" table:visibility="collapse">'
        + _text_cell("內部備註", "ce_label")
        + _text_cell(f"這一列是隱藏的（sample {sample_no}）", "ce_plain")
        + _empty(2)
        + "</table:table-row>"
    )

    # 第 4 列：表頭
    rows.append(
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("勤區", "ce_header")
        + _text_cell("姓名", "ce_header")
        + _text_cell("時數", "ce_header")
        + _text_cell("完成率", "ce_header")
        + "</table:table-row>"
    )

    # 第 5 列起：重複列區（筆數三份樣本各不同），A 欄縱向合併整個區塊
    for idx, (zone, name, hours, rate) in enumerate(staff):
        cells = []
        if idx == 0:
            cells.append(
                _text_cell(
                    zone,
                    "ce_merge_v",
                    table__number_columns_spanned="1",
                    table__number_rows_spanned=str(len(staff)),
                )
            )
        else:
            cells.append(_covered())
        cells.append(_text_cell(name, "ce_plain"))
        cells.append(_num_cell(hours, "ce_int"))
        cells.append(_num_cell(rate, "ce_pct"))
        rows.append('<table:table-row table:style-name="ro_default">' + "".join(cells) + "</table:table-row>")

    # 合計列：同表 SUM 公式
    first = 5
    last = 4 + len(staff)
    total = sum(s[2] for s in staff)
    rows.append(
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("合計", "ce_header")
        + _empty()
        + _formula_cell(f"of:=SUM([.C{first}:.C{last}])", total, "ce_int")
        + _empty()
        + "</table:table-row>"
    )

    duty_rows = "".join(rows)

    # 第二張表：跨表參照 + 兩位小數
    avg = round(sum(s[2] for s in staff) / len(staff), 2)
    stats_rows = (
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("項目", "ce_header")
        + _text_cell("數值", "ce_header")
        + "</table:table-row>"
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("總時數（跨表）", "ce_plain")
        + _formula_cell(f"of:=[$'勤務表'.C{last + 1}]", total, "ce_int")
        + "</table:table-row>"
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("平均時數", "ce_plain")
        + _num_cell(avg, "ce_dec2")
        + "</table:table-row>"
    )

    # 第三張表：隱藏工作表
    config_rows = (
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("設定鍵", "ce_header")
        + _text_cell("值", "ce_header")
        + "</table:table-row>"
        '<table:table-row table:style-name="ro_default">'
        + _text_cell("template_version", "ce_plain")
        + _text_cell(f"v{sample_no}", "ce_plain")
        + "</table:table-row>"
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS} office:version="1.2">
{STYLES}
  <office:body>
    <office:spreadsheet>
      <table:table table:name="勤務表" table:style-name="ta_visible">
        <table:table-column table:style-name="co_wide"/>
        <table:table-column table:style-name="co_default"/>
        <table:table-column table:style-name="co_narrow"/>
        <table:table-column table:style-name="co_default" table:visibility="collapse"/>
        {duty_rows}
      </table:table>
      <table:table table:name="統計" table:style-name="ta_visible">
        <table:table-column table:style-name="co_wide"/>
        <table:table-column table:style-name="co_default"/>
        {stats_rows}
      </table:table>
      <table:table table:name="設定" table:style-name="ta_hidden">
        <table:table-column table:style-name="co_default" table:number-columns-repeated="2"/>
        {config_rows}
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="settings.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

STYLES_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {NS} office:version="1.2">
  <office:styles/>
  <office:automatic-styles/>
  <office:master-styles/>
</office:document-styles>
"""

SETTINGS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-settings {NS} office:version="1.2">
{SETTINGS}
</office:document-settings>
"""

META_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta {NS} xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.2">
  <office:meta><meta:generator>docengine-fixture-builder</meta:generator></office:meta>
</office:document-meta>
"""


def write_ods(path: Path, content_xml: str) -> None:
    """組出一個合法的 ODF 封裝。

    ``mimetype`` 必須是 zip 的第一個項目且不壓縮——這是 ODF 規範用來讓檔案類型偵測
    只讀前幾個位元組就成立的機制。先前用 flat XML (.fods) 時 LibreOffice 把它誤判成
    Writer 文件而拒絕轉檔，就是缺了這個訊號。
    """
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/vnd.oasis.opendocument.spreadsheet",
            compress_type=zipfile.ZIP_STORED,
        )
        z.writestr("META-INF/manifest.xml", MANIFEST)
        z.writestr("content.xml", content_xml)
        z.writestr("styles.xml", STYLES_XML)
        z.writestr("settings.xml", SETTINGS_XML)
        z.writestr("meta.xml", META_XML)


#: 三份同型樣本。人員筆數刻意不同（3/4/2），才能驗「重複列區筆數會變」這件事。
SAMPLES = [
    (1, "2026-08-20", [("石牌", "王小明", 8, 92.5), ("石牌", "李大華", 6, 88.0), ("石牌", "陳美玲", 8, 95.0)]),
    (2, "2026-08-21", [("明德", "張志豪", 8, 90.0), ("明德", "林淑芬", 7, 85.5), ("明德", "黃建國", 8, 97.5), ("明德", "吳佩珊", 4, 78.0)]),
    (3, "2026-08-22", [("天母", "劉俊傑", 8, 93.0), ("天母", "蔡雅婷", 8, 91.5)]),
]


def main() -> int:
    if shutil.which("soffice") is None:
        print("找不到 soffice。fixture 必須由 LibreOffice 產生（AD-002），無法用本專案 renderer 代替。", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for no, date, staff in SAMPLES:
            ods = tmp_path / f"duty_roster_sample_{no}.ods"
            write_ods(ods, build_fods(no, staff, date))
            proc = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "-env:UserInstallation=file://" + str(tmp_path / "loprofile"),
                    "--convert-to",
                    "xlsx:Calc MS Excel 2007 XML",
                    "--outdir",
                    str(tmp_path),
                    str(ods),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            produced = tmp_path / f"duty_roster_sample_{no}.xlsx"
            if proc.returncode != 0 or not produced.exists():
                print(f"LibreOffice 轉檔失敗 (sample {no}):\n{proc.stdout}\n{proc.stderr}", file=sys.stderr)
                return 1
            target = OUT_DIR / produced.name
            shutil.copy2(produced, target)
            print(f"產生 {target.relative_to(PROJECT_ROOT)}  ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
