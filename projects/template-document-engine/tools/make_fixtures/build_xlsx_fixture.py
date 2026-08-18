"""XLSX golden fixture 產生器｜直接寫出原始 OOXML。

**這支程式刻意不共用 renderer 的任何一行程式碼**（AD-002）。理由：round-trip 測試若拿我們
renderer 寫出來的檔案當輸入，就只證明「renderer 和 parser 互相自洽」，證明不了 parser 讀得懂
真正的 Excel。原訂做法是讓 LibreOffice 轉檔，但本機沒裝 `libreoffice-calc`，試算表一律載入失敗。

替代做法是把 Excel 的編碼慣例寫死在這裡，而且刻意選 renderer **不會**自然產生的形式：

- 字串走 sharedStrings 索引（`t="s"`），另有一格走 `inlineStr`——兩種字串編碼並存。
- 欄位稀疏：空格直接不寫 `<c>`，而不是寫一個空的。
- 樣式索引刻意非連續、非遞增。
- `<row>` 帶 `spans`；`<cols>` 用 min/max 區段涵蓋多欄。
- 布林 `t="b"`、錯誤 `t="e"`、日期以序列數字 + numFmt 表示。
- 刻意放入 `definedNames` 與 `conditionalFormatting` 兩個**我們不建模**的元素，
  用來證明未支援特徵登記簿（AD-004）真的會觸發，而不是一個從沒被驗證過的空 list。

fixture 涵蓋 ACCEPTANCE_AND_EVIDENCE.md §2 列的難點：多工作表、隱藏工作表、橫向與縱向合併、
公式與跨表參照、數值/日期格式、列高欄寬、隱藏列欄、凍結窗格、多種框線、筆數會變動的重複列區。

io: in=無; out=fixtures/xlsx/duty_roster_sample_{1,2,3}.xlsx
依賴: 只用標準函式庫
用法: python3 tools/make_fixtures/build_xlsx_fixture.py
"""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "fixtures" / "xlsx"

#: Excel 的日期序列原點。1900 閏年 bug 讓 1899-12-30 成為實際的第 0 天。
EPOCH = dt.date(1899, 12, 30)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="{REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="{REL_NS}/worksheet" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Type="{REL_NS}/worksheet" Target="worksheets/sheet3.xml"/>
<Relationship Id="rId4" Type="{REL_NS}/sharedStrings" Target="sharedStrings.xml"/>
<Relationship Id="rId5" Type="{REL_NS}/styles" Target="styles.xml"/>
</Relationships>"""

# definedNames 是刻意放的：我們不建模它，所以它必須出現在未支援登記簿裡。
WORKBOOK = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
<workbookPr date1904="false"/>
<sheets>
<sheet name="勤務表" sheetId="1" r:id="rId1"/>
<sheet name="統計" sheetId="2" r:id="rId2"/>
<sheet name="設定" sheetId="3" state="hidden" r:id="rId3"/>
</sheets>
<definedNames><definedName name="_xlnm.Print_Area" localSheetId="0">'勤務表'!$A$1:$D$12</definedName></definedNames>
</workbook>"""

# 樣式表。cellXfs 的索引就是 <c s="..."> 指到的東西。
# 索引 0 是預設，之後刻意讓 fixture 用到 6/2/4/1/5/3 這種非遞增順序。
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2">
<numFmt numFmtId="164" formatCode="0.0%"/>
<numFmt numFmtId="165" formatCode="yyyy&quot;年&quot;m&quot;月&quot;d&quot;日&quot;"/>
</numFmts>
<fonts count="4">
<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="16"/><color rgb="FF1F3864"/><name val="Noto Sans CJK TC"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><i/><sz val="11"/><color rgb="FFC00000"/><name val="Calibri"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFDBE5F1"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="4">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FF999999"/></left><right style="thin"><color rgb="FF999999"/></right><top style="thin"><color rgb="FF999999"/></top><bottom style="thin"><color rgb="FF999999"/></bottom><diagonal/></border>
<border><left style="medium"><color rgb="FF1F3864"/></left><right style="medium"><color rgb="FF1F3864"/></right><top style="medium"><color rgb="FF1F3864"/></top><bottom style="medium"><color rgb="FF1F3864"/></bottom><diagonal/></border>
<border><left style="dashed"><color rgb="FFFF0000"/></left><right/><top/><bottom style="double"><color rgb="FF000000"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="7">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="14" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="3" xfId="0" applyFont="1" applyBorder="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
</cellXfs>
</styleSheet>"""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _serial(iso: str) -> int:
    return (dt.date.fromisoformat(iso) - EPOCH).days


class SharedStrings:
    """Excel 的字串池。刻意保留插入順序與重複去除，讓索引跟真檔一樣不直觀。"""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._index: dict[str, int] = {}
        self.total_refs = 0

    def index(self, text: str) -> int:
        self.total_refs += 1
        if text not in self._index:
            self._index[text] = len(self._items)
            self._items.append(text)
        return self._index[text]

    def to_xml(self) -> str:
        body = "".join(f"<si><t>{_esc(t)}</t></si>" for t in self._items)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<sst xmlns="{MAIN_NS}" count="{self.total_refs}" uniqueCount="{len(self._items)}">{body}</sst>'
        )


def _c_shared(ref: str, style: int, sst: SharedStrings, text: str) -> str:
    return f'<c r="{ref}" s="{style}" t="s"><v>{sst.index(text)}</v></c>'


def _c_inline(ref: str, style: int, text: str) -> str:
    """inlineStr：Excel 偶爾會用的另一種字串編碼。parser 必須兩種都認得。"""
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{_esc(text)}</t></is></c>'


def _c_num(ref: str, style: int, value: float) -> str:
    return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'


def _c_date(ref: str, style: int, iso: str) -> str:
    return f'<c r="{ref}" s="{style}"><v>{_serial(iso)}</v></c>'


def _c_bool(ref: str, style: int, value: bool) -> str:
    return f'<c r="{ref}" s="{style}" t="b"><v>{1 if value else 0}</v></c>'


def _c_error(ref: str, style: int, code: str) -> str:
    return f'<c r="{ref}" s="{style}" t="e"><v>{code}</v></c>'


def _c_formula(ref: str, style: int, formula: str, cached: float) -> str:
    return f'<c r="{ref}" s="{style}"><f>{_esc(formula)}</f><v>{cached}</v></c>'


def build_sheet1(staff: list[tuple[str, str, int, float]], report_date: str, sample_no: int, sst: SharedStrings) -> str:
    first_staff_row = 5
    last_staff_row = 4 + len(staff)
    total_row = last_staff_row + 1
    total_hours = sum(s[2] for s in staff)
    zone = staff[0][0]

    rows: list[str] = []

    # 第 1 列：標題（A1:D1 橫向合併）。ht/customHeight 是列高證據。
    rows.append(
        f'<row r="1" spans="1:4" ht="33" customHeight="1">'
        + _c_shared("A1", 6, sst, f"臺北市政府警察局　勤務分配表（第 {sample_no} 版）")
        + "</row>"
    )
    # 第 2 列：日期 + 隱藏欄 D 的內部註記。B2 用內建日期格式 14，D2 走 inlineStr。
    rows.append(
        '<row r="2" spans="1:4">'
        + _c_shared("A2", 5, sst, "報表日期")
        + _c_date("B2", 2, report_date)
        + _c_inline("D2", 4, f"internal-{sample_no}")
        + "</row>"
    )
    # 第 3 列：隱藏列。C3 是布林、D3 是錯誤值——兩種少見但合法的 cell type。
    rows.append(
        '<row r="3" spans="1:4" hidden="1">'
        + _c_shared("A3", 5, sst, "內部備註")
        + _c_shared("B3", 4, sst, f"這一列是隱藏的（sample {sample_no}）")
        + _c_bool("C3", 4, True)
        + _c_error("D3", 4, "#N/A")
        + "</row>"
    )
    # 第 4 列：表頭
    rows.append(
        '<row r="4" spans="1:4">'
        + "".join(_c_shared(f"{col}4", 1, sst, label) for col, label in zip("ABCD", ("勤區", "姓名", "時數", "完成率")))
        + "</row>"
    )
    # 重複列區：A 欄縱向合併整區，只有第一列有值，其餘不寫 <c>（稀疏）。
    for i, (_zone, name, hours, rate) in enumerate(staff):
        r = first_staff_row + i
        cells = [_c_shared(f"A{r}", 4, sst, zone)] if i == 0 else []
        cells.append(_c_shared(f"B{r}", 4, sst, name))
        cells.append(_c_num(f"C{r}", 4, hours))
        cells.append(_c_num(f"D{r}", 3, round(rate / 100, 4)))
        rows.append(f'<row r="{r}" spans="1:4">' + "".join(cells) + "</row>")
    # 合計列：同表 SUM
    rows.append(
        f'<row r="{total_row}" spans="1:4">'
        + _c_shared(f"A{total_row}", 1, sst, "合計")
        + _c_formula(f"C{total_row}", 4, f"SUM(C{first_staff_row}:C{last_staff_row})", total_hours)
        + "</row>"
    )

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
<dimension ref="A1:D{total_row}"/>
<sheetViews><sheetView tabSelected="1" workbookViewId="0"><pane xSplit="1" ySplit="4" topLeftCell="B5" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="15"/>
<cols><col min="1" max="1" width="18.5" customWidth="1"/><col min="2" max="2" width="12" customWidth="1"/><col min="3" max="3" width="7.25" customWidth="1"/><col min="4" max="4" width="9.140625" hidden="1" customWidth="1"/></cols>
<sheetData>{''.join(rows)}</sheetData>
<mergeCells count="2"><mergeCell ref="A1:D1"/><mergeCell ref="A{first_staff_row}:A{last_staff_row}"/></mergeCells>
<conditionalFormatting sqref="C{first_staff_row}:C{last_staff_row}"><cfRule type="cellIs" dxfId="0" priority="1" operator="greaterThan"><formula>7</formula></cfRule></conditionalFormatting>
<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>"""


def build_sheet2(staff: list[tuple[str, str, int, float]], sst: SharedStrings) -> str:
    total = sum(s[2] for s in staff)
    avg = round(total / len(staff), 2)
    duty_total_row = 5 + len(staff)
    rows = [
        '<row r="1" spans="1:2">'
        + _c_shared("A1", 1, sst, "項目")
        + _c_shared("B1", 1, sst, "數值")
        + "</row>",
        '<row r="2" spans="1:2">'
        + _c_shared("A2", 4, sst, "總時數（跨表）")
        + _c_formula("B2", 4, f"勤務表!C{duty_total_row}", total)
        + "</row>",
        '<row r="3" spans="1:2">' + _c_shared("A3", 4, sst, "平均時數") + _c_num("B3", 4, avg) + "</row>",
    ]
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
<dimension ref="A1:B3"/>
<sheetViews><sheetView workbookViewId="0"/></sheetViews>
<sheetFormatPr defaultRowHeight="15"/>
<cols><col min="1" max="1" width="18.5" customWidth="1"/><col min="2" max="2" width="12" customWidth="1"/></cols>
<sheetData>{''.join(rows)}</sheetData>
<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>"""


def build_sheet3(sample_no: int, sst: SharedStrings) -> str:
    rows = [
        '<row r="1" spans="1:2">' + _c_shared("A1", 1, sst, "設定鍵") + _c_shared("B1", 1, sst, "值") + "</row>",
        '<row r="2" spans="1:2">'
        + _c_shared("A2", 4, sst, "template_version")
        + _c_shared("B2", 4, sst, f"v{sample_no}")
        + "</row>",
    ]
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
<dimension ref="A1:B2"/>
<sheetViews><sheetView workbookViewId="0"/></sheetViews>
<sheetFormatPr defaultRowHeight="15"/>
<cols><col min="1" max="2" width="16" customWidth="1"/></cols>
<sheetData>{''.join(rows)}</sheetData>
<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>"""


def build_workbook(path: Path, sample_no: int, report_date: str, staff: list[tuple[str, str, int, float]]) -> None:
    sst = SharedStrings()
    sheet1 = build_sheet1(staff, report_date, sample_no, sst)
    sheet2 = build_sheet2(staff, sst)
    sheet3 = build_sheet3(sample_no, sst)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        z.writestr("xl/styles.xml", STYLES)
        z.writestr("xl/sharedStrings.xml", sst.to_xml())
        z.writestr("xl/worksheets/sheet1.xml", sheet1)
        z.writestr("xl/worksheets/sheet2.xml", sheet2)
        z.writestr("xl/worksheets/sheet3.xml", sheet3)


#: 三份同型樣本。人員筆數刻意不同（3/4/2），才驗得到「重複列區筆數會變」。
SAMPLES = [
    (1, "2026-08-20", [("石牌", "王小明", 8, 92.5), ("石牌", "李大華", 6, 88.0), ("石牌", "陳美玲", 8, 95.0)]),
    (
        2,
        "2026-08-21",
        [("明德", "張志豪", 8, 90.0), ("明德", "林淑芬", 7, 85.5), ("明德", "黃建國", 8, 97.5), ("明德", "吳佩珊", 4, 78.0)],
    ),
    (3, "2026-08-22", [("天母", "劉俊傑", 8, 93.0), ("天母", "蔡雅婷", 8, 91.5)]),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for no, date, staff in SAMPLES:
        target = OUT_DIR / f"duty_roster_sample_{no}.xlsx"
        build_workbook(target, no, date, staff)
        print(f"產生 {target.relative_to(PROJECT_ROOT)}  ({target.stat().st_size} bytes, {len(staff)} 筆人員)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
