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

## AD-002 — Golden fixture 由 LibreOffice 產生，不得由本專案的 renderer 產生

**脈絡.** round-trip 測試是 `parse → IR → render → parse → diff`。如果 fixture 本身是我們的 renderer
寫出來的，這個測試只證明「我們的 renderer 和我們的 parser 互相自洽」，證明不了 parser 讀得懂真正的
Excel/Word。那是一個看起來全綠的空心閘。

**決定.** `fixtures/xlsx/` 與 `fixtures/docx/` 底下的 `.xlsx` / `.docx` 一律由 LibreOffice（本機
24.2.7.2）從 `tools/make_fixtures/*.fods` / `*.fodt` 這類 flat-XML 來源轉出，或由手寫的原始 OOXML 打包
而成——兩條路都獨立於本專案的 renderer。產生指令記在 `fixtures/MANIFEST.md`，可重現。

`ARCHITECTURE.md` §5 說「Do not use LibreOffice as the core parser」。本決定不違反：LibreOffice 只當
fixture 生產者，不在執行路徑上。

**代價.** fixture 重生成需要 LibreOffice；CI 若沒有它就只能用已 commit 的二進位 fixture。因此 fixture
檔案本身要進版控，並標記 `@pytest.mark.libreoffice` 區隔「重新生成」與「讀取既有 fixture」兩種測試。

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
