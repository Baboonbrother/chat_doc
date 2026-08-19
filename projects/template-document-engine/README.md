# Template-Guided Document Generation Engine — Blueprint

這是一份可直接交給 Claude Code 執行的工程藍圖。

## 產品定義

本系統不是一般「格式轉換器」。它要做到：

1. 接收多份同類型 Word (`.docx`) / Excel (`.xlsx`) 範本。
2. 確定性反向解析頁面、段落、表格、合併格、樣式、公式、欄列幾何等格式。
3. 對多份樣本做對齊，分辨固定內容與動態內容。
4. 使用本地 LLM 處理不能可靠靠規則完成的工作：欄位語意、資料映射、慣用語抽取、受控文字生成。
5. 把結果編譯成可版本化的 `Template Profile`。
6. 將任意新資料正規化成 `Canonical Data`。
7. 將 `Canonical Data + Template Profile` 生成新的 Word/Excel。
8. 再用確定性的 round-trip、結構、樣式、內容與語意驗證證明輸出是否合格。

核心原則：

> 規則處理可以確定的事情；LLM 處理需要理解的事情；LLM 的語意判斷預設是 proposal，能驗證的部分一定再由 deterministic validator 驗證。

## 三個核心 IR / Contract

- `Document IR`：描述「這一份文件現在長什麼樣」。
- `Template Profile`：描述「這一類文件應該怎麼生成」。
- `Canonical Data`：描述「本次要填入的業務資料是什麼」，與輸入檔案格式解耦。

## 本地 LLM

本藍圖明確要求支援至少兩個可插拔本地模型：

- Qwen 27B
- ORINTH 9B

實際 model id、host、port 不可寫死。預設以 OpenAI-compatible HTTP API 方式接入；若本地 runtime 不相容，新增 adapter，但核心只呼叫統一 `LLM Gateway`。

不可先假定 27B 一定在所有工作都比 9B 好。必須用 benchmark corpus 評估：

- semantic field inference
- field mapping
- terminology/pattern extraction
- controlled text generation
- structured JSON valid rate
- latency
- retry rate

最後再以 benchmark 建 `Model Router`。

## Claude Code 的開工順序

請先讀：

1. `ARCHITECTURE.md`
2. `LLM_GATEWAY.md`
3. `SCHEMAS_AND_CONTRACTS.md`
4. `ACCEPTANCE_AND_EVIDENCE.md`
5. `TASK_REGISTRY.yaml`
6. `CLAUDE_CODE_EXECUTION.md`

不要直接從 UI 開始。v0.1 的最小可用介面是 CLI：

```bash
docengine inspect sample.xlsx
docengine learn ./samples --out template_profile.json
docengine generate --template template_profile.json --input data.json --output result.xlsx
docengine validate --template template_profile.json --document result.xlsx
docengine benchmark --models qwen27b,orinth9b
```

CLI 成功並通過 golden tests 後，才允許新增 HTTP API；UI 不屬於 v0.1 必要範圍。

## 任務圖

`TASK_REGISTRY.yaml` 目前定義 92 個節點，分為：

- Foundation
- XLSX Parser/Renderer
- DOCX Parser/Renderer
- Template Learning
- Local LLM Gateway / Benchmark / Routing
- Input Ingestion / Canonicalization
- Generation
- Validation
- Integration / Release Gate

每一個節點都有：

- `kind`: `DETERMINISTIC | LLM | HYBRID`
- `depends_on`
- `objective`
- `acceptance`
- `status`

完成節點不能只把 `status` 改成 `DONE`，必須附 implementation/test/evidence。

## 不可偷換需求

以下實作視為錯誤：

- 只複製 Excel 再改幾個 cell。
- 直接把整份文件交給 LLM，讓 LLM 自己決定 merge、row height、font、border。
- 用大量 if/else 假裝解決語意推論節點。
- 把「模型回了一個 JSON」當成語意正確。
- 只有單一樣本卻假裝已經學到「固定 vs 變動」規則。
- 只支援一個 model 並把 model name 寫死。
- 沒有 source provenance、confidence、unknown/review state。
- 產出檔案能打開就算通過。
- 沒有 round-trip validation。
- 沒有 benchmark 就自行指定所有 task 都跑 27B。

## v0.1 Done 的定義

必須至少證明兩條 golden scenario：

**XLSX**
多份同型 Excel → learn profile → 新資料 → regenerate → round-trip / structure / style / semantic checks 通過。

**DOCX**
多份同型 Word → learn profile → 新資料 → regenerate → round-trip / structure / style / semantic checks 通過。

此外還要有 Qwen 27B 與 ORINTH 9B 的同 corpus A/B benchmark 報告。

這個 blueprint 的目的不是讓 Claude Code「照文件寫一些程式」，而是讓它沿著可驗收 DAG 一個節點一個節點完成。