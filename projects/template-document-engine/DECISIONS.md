# Architectural Decision Records

實作過程中偏離、細化或補強藍圖的決定都記在這裡。藍圖（`ARCHITECTURE.md` 等六份）是需求真相源；
這份是「實作為什麼長這樣」的真相源。每筆決定要寫清楚：脈絡、決定、代價、以及怎麼推翻它。

---

## AD-001 — OOXML 用 stdlib `zipfile` + `xml.etree`，不用 openpyxl / python-docx

**脈絡.** `ARCHITECTURE.md` §5 建議 `openpyxl` 與 `python-docx`。實測本機兩者都沒安裝，且系統 Python
是 PEP 668 externally-managed，安裝需另建 venv。更關鍵的是：本系統的賣點是「精確格式由 deterministic
parser/renderer 負責」，而這兩個函式庫對這個目標都是有損的——`openpyxl` 讀寫時會整份重建 `styles.xml`
並丟棄它不認識的 part；`python-docx` 只暴露 OOXML 的一個子集，藍圖自己也寫了「plus direct OOXML access
where python-docx does not expose enough detail」。把「精確」蓋在一個會靜默丟東西的層上，是把最重要的
不變式交給我們控制不到的程式碼。

**決定.** parser 與 renderer 直接處理 OOXML：`zipfile` 讀 package、`xml.etree.ElementTree` 讀寫 XML。
契約層（Document IR / Template Profile / Canonical Data）用 `pydantic`（本機已安裝，非新增安裝）。
`jsonschema` 只在測試裡用來驗 schema 匯出。

**代價.** 程式碼多很多，OOXML 的細節（sharedStrings、styles 索引、date serial、r:id 關聯）要自己處理，
而且我們對真實世界怪檔案的耐受度不如身經百戰的函式庫。這個代價用 AD-004 的未支援特徵登記簿來承擔：
不認識的東西必須被記錄，不能靜默丟掉。

**怎麼推翻.** 若之後要吃進大量真實世界的檔案而 stdlib parser 的耐受度成為瓶頸，可在 `parsers/` 下加一個
以 openpyxl 為後端的 adapter，但它必須通過同一組 round-trip golden test 才准取代。

---

## AD-002 — Golden fixture 不得由本專案的 renderer 產生（原訂 LibreOffice 路線已因環境受阻，改雙軌）

**脈絡.** round-trip 測試是 `parse → IR → render → parse → diff`。如果 fixture 本身是我們的 renderer
寫出來的，這個測試只證明「我們的 renderer 和我們的 parser 互相自洽」，證明不了 parser 讀得懂真正的
Excel/Word。那是一個看起來全綠的空心閘。

**原訂決定.** 用 LibreOffice 把手寫的 ODF 轉成 `.xlsx` / `.docx`。

**實測受阻.** 本機 LibreOffice 24.2.7.2 只裝了 `libreoffice-writer` 與 `libreoffice-math`，
**沒有 `libreoffice-calc`**。任何試算表載入都失敗（`Error: source file could not be loaded`），
先前 `.fods` 被誤判成 Writer 文件也是同一個原因。DOCX 那一側則不受影響，Writer 可用。

**改後決定（雙軌）.**

1. **進版控的 fixture**：由 `tools/make_fixtures/build_xlsx_fixture.py` 直接寫出原始 OOXML。
   它是一份**獨立於 renderer 的產生器**：刻意採用 Excel 的編碼慣例而非我們 renderer 的偏好——
   sharedStrings 索引式字串、`inlineStr`、稀疏欄位（跳過空格）、非連續的樣式索引、`spans` 屬性、
   `t="b"`／`t="e"`、`cols` 用 min/max 區段，並刻意放入 `definedNames` 與 `conditionalFormatting`
   兩個我們**不打算建模**的元素，用來證明未支援登記簿（AD-004）真的會觸發。
2. **不進版控的真實語料**：本機有 49 份由 Microsoft Excel 產生的真實 `.xlsx`。
   `tests/test_xlsx_real_corpus.py` 會在環境變數 `DOCENGINE_REAL_XLSX_DIR` 指到目錄時，
   對它們跑 parse → render → parse → diff。**這些檔案含公務與個人資料，而本 repo 是公開的，
   因此絕對不進版控**；沒設環境變數時測試 skip。

**代價.** 進版控那一軌的「第三方性」比原訂弱：產生器仍是我寫的，可能無意識地只寫出我的 parser 看得懂的
形狀。真正的第三方保證來自第二軌，但它不可重現於 CI。要把兩者合一，需要
`sudo apt install libreoffice-calc`（系統變更，需 owner 同意）。

**怎麼推翻.** 裝上 `libreoffice-calc` 後，把 fixture 產生器改回 ODF→XLSX 轉檔路線
（該版程式碼保留在本 commit 的 git 歷史裡），並讓兩軌都跑。

---

## AD-003 — Style ID 是內容雜湊，不是原始 styles.xml 的索引

**脈絡.** XLSX 的 cell 用 `s="12"` 指向 `cellXfs` 的第 12 個項目。DOCX 的 style 用名字。如果 IR 直接沿用
索引，那 render 後 `cellXfs` 的排列順序一變，重新 parse 出來的 style ref 就不一樣，round-trip diff 會
因為「同一個樣式換了編號」而假紅。

**決定.** IR 的 `styles` 是一張 `style:<sha256前16碼>` → 樣式內容的表，ID 由正規化後的樣式內容算出。
同樣的字型／填滿／框線／對齊／數值格式，不論在哪一份文件、排在第幾個，都得到同一個 ID。

**代價.** ID 不再能反查原始索引，所以 `source_ref` 必須另外保留原始索引供稽核。

---

## AD-004 — 未支援特徵必須登記，不得靜默丟棄

**脈絡.** 任何「只模型化一部分 OOXML」的 parser 都會遇到不認識的元素。靜默丟棄會讓 round-trip 測試通過
（因為兩邊都沒有它），卻讓使用者拿到一份少東西的檔案。這是本專案最容易出現的假成功。

**決定.** IR 增加 `unsupported: [UnsupportedFeature]`。parser 遇到已知但未模型化的元素時，記下
part、XML 路徑、元素名稱與計數。round-trip 報告必須把它印出來，`ACCEPTANCE_AND_EVIDENCE.md` §3 要求的
「explicitly declare tolerances and unsupported OOXML features」由此滿足。

**代價.** parser 每個分支都要多寫一段「其餘記到登記簿」，而且登記簿本身會參與 diff。

---

## AD-007 — renderer 依「原始子元素序列」組裝，不依 schema 順序表

**脈絡.** 第一版 renderer 把每個 part 的內容收集成「標籤 → XML 區塊」的字典，再依 OOXML schema
的順序表輸出。拿 40 份真實 Microsoft Excel 檔一跑，33 份重建後壞掉或少東西。

兩個原因，都是靜默遺失：

1. **順序表上沒有的標籤會被丟掉。** `mc:AlternateContent` 不在 `CT_Workbook` 的 sequence 裡
   （它是 markup-compatibility 的東西，可以出現在任何位置），於是整段消失。
2. **同名元素會互相覆蓋。** 一張工作表可以有多個 `conditionalFormatting`；用標籤當字典鍵，
   只會留下最後一個。

**決定.** parser 額外記錄每個 part 的原始子元素標籤序列（`child_sequence`），renderer 依它組裝：
逐一走過原始順序，遇到已建模的標籤就輸出我們重建的區塊，遇到逐字保留的就依序取出。
沒有 `child_sequence`（程式合成的新文件）才退回 schema 順序表。最後還有一道兜底：
任何沒被輸出的片段一律補在尾端——寧可順序不完美，也不要靜默少東西。

**代價.** `child_sequence` 是 IR 的一部分，會參與 diff，所以「元素順序變了」也會讓 round-trip 轉紅。
這是想要的行為，但它讓 IR 對格式細節更敏感。

---

## AD-008 — 「選配元素」不得無中生有

**脈絡.** `<dimension>`（涵蓋範圍）與 `<workbookPr>` 都是選配的。renderer 一律產生它們，
於是來源沒有的檔案在重建後多出東西，round-trip 因為「我們自己加的」而轉紅。
`workbookPr` 更糟：真實檔案的它帶著 `defaultThemeVersion` 等我們不理解的屬性，
我們用一個只有 `date1904` 的版本覆蓋過去，等於靜默改寫。

**決定.** 選配元素只在來源本來就有時才輸出。`workbookPr` 從「已建模」降級為「逐字保留」——
我們只從它**讀**出 `date1904`，不重寫它。`dimension` 相反：它是純衍生資訊，來源有就重算後輸出，
來源沒有就不生。

**代價.** renderer 多了「來源有沒有這個元素」的分支；合成新文件時要自己決定要不要產生它們。

---

## AD-009 — 未支援登記的數量必須參與比對

**脈絡.** diff 一開始用 `(part, element)` 當未支援登記的比對鍵。實測時出現一個 diff 說「相等」、
獨立的結構雜湊卻說「不同」的案例：來源有 11 筆富文字、重建後剩 10 筆，而 diff 完全看不見。

**決定.** 比對鍵加入 `count` 與 `note`。同時 round-trip 的 `passed` 要求 **diff 相等且結構雜湊相同**——
兩個獨立證據，避免把驗證全押在 diff 的實作上。這次就是雜湊救了 diff。

**附帶發現.** 那個 11 vs 10 的差距本身不是遺失：字串池裡有沒被任何儲存格引用的舊項目，
renderer 只寫出被引用到的。於是登記量改成「IR 實際承載幾格富文字」，
而「丟掉幾筆無人引用的字串」則記進 `metadata.normalizations` 並印在 round-trip 報告的
「已宣告的正規化」段——刻意的改變要講出來，不能讓使用者自己發現檔案變小了。

---

## AD-005 — 本機模型別名對應（可設定，不寫死）

**脈絡.** 藍圖要求支援 `qwen27b` 與 `orinth9b` 兩個概念別名，且 model id / endpoint 不可寫死。

**決定.** 本機實際可用的是 Ollama（`http://127.0.0.1:11434`，版本 0.32.13），提供 OpenAI-compatible
端點 `/v1`。預設對應寫在 `config/models.yaml`（可被環境變數與 CLI 參數覆寫）：

| 概念別名 | 本機 model id | 備註 |
| --- | --- | --- |
| `qwen27b` | `qwen3.6:27b` | 本機另有 `qwen3.8:27b-local`、`qwen3.8:27b-hermes` 可換 |
| `orinth9b` | `ornith:9b` | 藍圖寫 ORINTH，本機 tag 是 `ornith` |

**代價.** 別名與實體 model 的對應是設定，benchmark 報告必須把實際 model id 一起記下來，否則跨次比較會
比到不同模型。

---

## AD-006 — Document IR 把 merged region 與 column 定義建模成節點

**脈絡.** `SCHEMAS_AND_CONTRACTS.md` 列的 node kind 是 `sheet | section | paragraph | run | table | row |
cell`，但同一份文件又要求「explicit merged regions and formulas」。合併區與欄寬不屬於任何一個 cell，掛在
sheet 的屬性裡則不好逐項 diff。

**決定.** 擴充 node kind，新增 `merged_region` 與 `column`（XLSX）。它們是 sheet 的子節點，有自己的
`source_ref`，因此可以逐項出現在 round-trip diff 裡。凍結窗格（freeze panes）屬於整張 sheet 的視圖狀態，
放在 sheet 節點的 `geometry`。

**代價.** node kind 集合比藍圖列的大。這是刻意的擴充，不是偏離；`document_ir/model.py` 的 `NodeKind`
就是唯一真相源。
