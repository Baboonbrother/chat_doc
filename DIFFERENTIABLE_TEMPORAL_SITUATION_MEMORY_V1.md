# Differentiable Temporal Situation Memory V1

> 狀態：設計基線（implementation-ready）  
> 目的：把來自 LINE、使用者手動輸入、Email、逐字稿、文件、OCR、API 等來源的破碎資訊，重建成可追溯、可回放、可修正、可自我改善的「時間化世界狀態」，最後才生成報告。

---

## 0. 核心結論

本系統**不是摘要器**，也不是把訊息丟進向量資料庫後做 RAG。

核心資料哲學：

```text
Evidence != Fact
Fact != Event
Event != Report
```

真正的資料流程：

```text
ANY SOURCE
  -> Source Adapter
  -> Evidence Record
  -> Atomic Situation Frame
  -> Entity / Frame Resolution
  -> Slot Delta
  -> Temporal Situation Memory
  -> Event Reconstruction
  -> Narrative / Report
```

其中：

1. **L0 Evidence**：原始證據，append-only，不被 LLM 改寫。
2. **L1 Differential Facts**：把每次新資訊表示成 slot 的微小變化（delta）。
3. **L2 Reconstruction**：在任意 `as_of` 時刻重建「當時知道的世界」。
4. **L3 Narrative**：最後才產生報告、摘要、事件說明。

可微分層只負責**不確定性判斷**（retrieval、matching、ranking、context routing），不能直接修改 canonical truth。

---

# 1. 需求

## 1.1 問題

通訊與工作紀錄常是破碎的：

```text
09:10 三樓冷氣好像壞了
09:30 已經叫廠商
14:20 師傅說可能是壓縮機
隔天 10:00 不是壓縮機，是控制板
15:30 修好了，3500
```

同一件事跨時間、跨訊息，甚至穿插其他主題；後面的訊息也可能補齊先前不知道的「人、事、時、地、物」。

不能直接：

```text
messages -> clustering -> summary
```

因為會發生：

- 同主題但不同事件被錯合。
- 文字不像但實際上是同一事件的後續被拆開。
- 後來的資訊污染早期的「當時認知」。
- 第一次摘要錯誤後，錯誤持續累積。
- LLM 不知道某欄位是「未知」還是「忘了抽」。

---

# 2. 核心資料單位：Atomic Situation Frame

最底層節點不是「一句摘要」，而是**完整槽位存在、只有部分槽位被填值的情境框架**。

例如：

```text
「三樓冷氣疑似異常」
```

不得只存：

```yaml
fact: 三樓冷氣疑似異常
```

而應表示：

```yaml
frame_type: EQUIPMENT_ABNORMALITY

who:
  observer: UNKNOWN
  reporter: EXPLICIT_OR_RESOLVED
  responsible_person: UNKNOWN

what:
  state: SUSPECTED_ABNORMAL
  symptom: UNKNOWN
  severity: UNKNOWN
  cause: UNKNOWN
  operational_impact: UNKNOWN

when:
  event_start_time: UNKNOWN
  observed_time: UNKNOWN
  reported_time: EXPLICIT

where:
  organization: UNKNOWN
  site: UNKNOWN
  building: UNKNOWN
  floor: 3F
  room: UNKNOWN
  area: UNKNOWN

object:
  equipment_type: AIR_CONDITIONER
  equipment_id: UNKNOWN
  model: UNKNOWN
  owner: UNKNOWN
```

**欄位存在本身也是資訊。**

---

# 3. UNKNOWN 不能只有 NULL

至少需要下列狀態：

```text
UNKNOWN          應該有答案，但目前不知道
NOT_MENTIONED    本筆 Evidence 未提到，不代表系統其他地方不知道
NOT_APPLICABLE   此 Frame 類型不適用此欄位
AMBIGUOUS        有候選，但目前無法唯一決定
CONFLICTING      多個證據互相衝突
EXPLICIT         原始 Evidence 明講
INFERRED         系統推論，不能假裝成原文
RESOLVED         原本未知，後來由新證據補齊
```

另外「有沒有講」與「事情有多確定」必須分開：

```text
knowledge_status != epistemic_status
```

Epistemic status 可包含：

```text
OBSERVED
REPORTED
SUSPECTED
INFERRED
PLANNED
CONFIRMED
DISPUTED
RETRACTED
SUPERSEDED
```

例如：

```text
「我覺得可能是控制板」
```

應是：

```yaml
knowledge_status: EXPLICIT
epistemic_status: SUSPECTED
```

不是 CONFIRMED。

---

# 4. 時間模型：至少雙時間軸

每一個 fact / slot delta 至少分：

```text
valid_time    事情在世界中何時成立 / 發生
known_time    系統何時知道這件事
```

例：8/18 才收到：

```text
「其實冷氣 8/16 晚上就開始有異音。」
```

應存：

```yaml
valid_time: 2026-08-16T21:00
known_time: 2026-08-18T09:00
```

因此系統必須支援：

```text
AS_KNOWN_THEN
WITH_CURRENT_ENTITY_RESOLUTION
```

並嚴格避免 future information leakage。

---

# 5. 微分資料模型：Slot Delta

Canonical frame 的目前狀態不是唯一歷史。

真正歷史由 append-only delta 組成：

```text
Frame(t) = Frame(t-1) + Sum(SlotDelta)
```

例如：

```text
D001 floor: UNKNOWN -> 3F
D018 building: UNKNOWN -> A棟
D033 cause: UNKNOWN -> 壓縮機故障 (SUSPECTED)
D052 cause: 壓縮機故障 -> 控制板故障 (CORRECT)
D071 repair_state: WAITING -> COMPLETED
D072 cost: UNKNOWN -> 3500
```

舊 delta 不修改；更正一律新增 delta。

操作型別：

```text
FILL
UPDATE
CORRECT
CONFIRM
DISPUTE
RETRACT
SUPERSEDE
CLEAR
```

---

# 6. Evidence 必須 source-agnostic

LINE 只是一個來源，不是 domain model。

來源可以是：

```text
USER_INPUT
LINE
EMAIL
SLACK
TRANSCRIPT
DOCUMENT
OCR
API
SYSTEM
SENSOR
HUMAN_CORRECTION
```

所有來源先轉成同一種 `EvidenceRecord`：

```text
evidence_id
source_type
source_id
author_entity_id nullable
conversation_id nullable
observed_at nullable
received_at
content_type
raw_text nullable
raw_payload_json nullable
parent_evidence_id nullable
quoted_evidence_id nullable
content_hash
created_at
```

Source Adapter 只做**格式標準化**，不能做事件推論。

推薦目錄：

```text
sources/
  user_input.py
  line.py
  email.py
  transcript.py
  document.py
  api.py
```

---

# 7. Canonical PostgreSQL tables

第一版以 PostgreSQL 為 canonical store。Vector DB / Graph DB 只能當索引或 traversal layer，不能當唯一 truth。

## 7.1 `evidence_records`

原始 Evidence，append-only。

核心欄位：

```text
evidence_id PK
source_type
source_id
author_entity_id
conversation_id
observed_at
received_at
content_type
raw_text
raw_payload_json
parent_evidence_id
quoted_evidence_id
content_hash
created_at
```

## 7.2 `evidence_links`

Evidence 間關係：

```text
REPLY_TO
QUOTES
DERIVED_FROM
TRANSCRIBED_FROM
OCR_FROM
CORRECTS
SUPPLEMENTS
```

## 7.3 `entities`

人、組織、地點、設備、廠商等 canonical entities。

```text
entity_id PK
entity_type
canonical_name
status
created_at
```

類型：

```text
PERSON
ORGANIZATION
SITE
BUILDING
FLOOR
ROOM
AREA
EQUIPMENT
VEHICLE
DOCUMENT
VENDOR
...
```

## 7.4 `entity_aliases`

例如：王小明 / 小王 / 王哥。

## 7.5 `entity_relations`

例如：

```text
ORGANIZATION
  CONTAINS -> SITE
  CONTAINS -> BUILDING
  CONTAINS -> FLOOR
  CONTAINS -> ROOM
  CONTAINS -> EQUIPMENT
```

Relation types：

```text
CONTAINS
LOCATED_IN
BELONGS_TO
WORKS_FOR
OWNS
RESPONSIBLE_FOR
SAME_AS
ALIAS_OF
```

關係需帶 valid/known time 與 provenance。

## 7.6 `frames`

Atomic Situation Frame metadata：

```text
frame_id PK
frame_type
frame_schema_version
state
created_from_evidence_id
valid_start
valid_end
known_start
known_end
created_at
```

## 7.7 `frame_slots`

目前 canonical slot projection。

**不要把所有槽位做成 frames 的固定 SQL columns。**

建議：

```text
slot_id PK
frame_id FK
slot_name
value_type
entity_value_id nullable
text_value nullable
number_value nullable
datetime_value nullable
json_value nullable
knowledge_status
epistemic_status
valid_from
valid_to
known_from
known_to
```

## 7.8 `slot_deltas`

歷史核心：

```text
delta_id PK
frame_id
slot_name
operation
old_value
new_value
old_status
new_status
valid_time
known_time
evidence_id
decision_id
created_at
```

## 7.9 `frame_relations`

Atomic Frames 之間的關係：

```text
CAUSES
MOTIVATES
RESULTS_IN
PRECEDES
FOLLOWS
CORRECTS
CONTRADICTS
SUPPORTS
PART_OF
SAME_INCIDENT
POSSIBLY_SAME_INCIDENT
```

## 7.10 `frame_evidence`

每個 frame / slot 可追回原始 Evidence 與原文 span。

## 7.11 `events`

Event 是較高階重建結果，不是底層事實。

```text
event_id PK
event_type
canonical_title
state
start_time
end_time
created_at
updated_at
```

## 7.12 `event_frames`

哪些 atomic frames 組成某 Event。

## 7.13 `unresolved_items`

任何 unresolved reference / frame / slot / merge / conflict 都必須進此表，而不是強迫 LLM 猜答案。

```text
unresolved_id PK
object_type
object_id
problem_type
candidate_json
status
first_seen_at
last_checked_at
retry_count
```

## 7.14 `decision_receipts`

每一次 LLM 認知判斷的完整收據：

```text
decision_id PK
task_type
input_evidence_id
context_bundle_hash
model
model_version
prompt_version
schema_version
retrieval_version
candidate_ids
decision_json
validator_result
created_at
```

## 7.15 `corrections`

人工修正不能直接偷偷 update database，必須形成 correction asset。

```text
correction_id PK
target_type
target_id
original_decision_id
old_value
corrected_value
error_type
reason
corrected_by
created_at
```

---

# 8. 可微分 / learning tables

為了之後真正學習 matching，而不是只有口號，再增加：

## 8.1 `model_scores`

每次 candidate ranking 保存特徵與最終 score：

```text
decision_id
candidate_type
candidate_id
semantic_score
entity_score
location_score
actor_score
temporal_score
open_slot_score
reply_score
correction_similarity_score
neural_score
final_score
rank
```

## 8.2 `training_examples`

由人工 correction / 高可信結果形成：

```text
example_id
task_type
input_id
positive_target_id
negative_target_ids
source
weight
created_at
```

## 8.3 `model_versions`

保存 scorer / reranker / context router 的版本、資料集 hash 與參數。

## 8.4 `evaluation_runs`

比較 baseline 與 candidate model：

```text
frame_accuracy
entity_accuracy
false_merge_rate
false_split_rate
unknown_precision
unknown_recall
slot_accuracy
promotion_result
```

---

# 9. Logical Graph：真正的節點與邊

SQL table 不等於 graph node。

主要 node 建議只保留：

```text
EVIDENCE
ENTITY
FRAME
EVENT
DECISION
REPORT
```

核心結構：

```text
EVIDENCE
   --SUPPORTS--> FRAME

FRAME
   --INVOLVES--> ENTITY

FRAME
   --CAUSES / FOLLOWS / CORRECTS--> FRAME

FRAME
   --PART_OF_EVENT--> EVENT

DECISION
   --GENERATED--> SLOT_DELTA

SLOT_DELTA
   --SUPPORTED_BY--> EVIDENCE
```

UNKNOWN **不是一個假的 entity node**；它是 slot 的狀態。

---

# 10. Typed Frame Schema

不要建立一個有 500 欄的超級 Frame。

應採：

```text
UNIVERSAL CORE
  who
  what
  when
  where
  object
  state
  change
  cause
  purpose
  method
  result
  epistemic
  provenance

+ TYPED FRAME SPECIFIC SLOTS
```

第一批建議 frame types：

```text
EQUIPMENT_ABNORMALITY
CONTACT_VENDOR
REPAIR_VISIT
REPAIR_DIAGNOSIS
REPAIR_QUOTATION
REPAIR_COMPLETION
PERSONNEL_LEAVE
SHIFT_CHANGE
DRIVER_ASSIGNMENT_CHANGE
MEETING_DECISION
DOCUMENT_NOTICE
ASSET_MOVEMENT
INCIDENT_REPORT
LOCATION_CHANGE
TASK_ASSIGNMENT
TASK_COMPLETION
```

Frame schema 由 code / versioned registry 管理。

LLM 不得自己直接新增 production schema；它只能提出 schema proposal，再經 replay 驗收。

---

# 11. 本地 LLM API 架構

上層不可綁死 Ollama。

定義自己的 gateway abstraction：

```text
StructuredLLM.generate_structured(
    system_prompt,
    user_payload,
    output_schema
) -> typed object
```

Adapter 可包含：

```text
OllamaStructuredLLM
VLLMStructuredLLM
OpenAICompatibleLLM
```

所有 Extractor / Resolver / Critic 只依賴 `StructuredLLM` interface。

Structured output 必須以 JSON Schema / Pydantic schema 驗證，不能只靠 prompt 說「請輸出 JSON」。

---

# 12. Local LLM 角色拆分

同一個模型可套不同 prompt，但責任必須分開。

## 12.1 EXTRACTOR

只回答：

```text
這個 Evidence 中有哪些最小 Atomic Frames？
```

禁止：

- 寫報告。
- 自由修改既有 memory。
- 推測原文沒提供的欄位。

## 12.2 RESOLVER

只回答：

```text
這些人 / 地 / 物 / frame 是否對應既有記憶？
```

決策只能：

```text
ATTACH
NEW
UNRESOLVED
NEED_MORE_CONTEXT
```

## 12.3 DELTA PROPOSER

只提出 slot mutation proposal。

## 12.4 CRITIC

檢查：

- 是否與 evidence 衝突。
- 是否把 inference 假裝成 explicit fact。
- 是否 future leakage。
- 是否可能錯 merge。

LLM 永遠只能 `propose_*`，不能直接 `update_database()`。

---

# 13. Frame Schema Registry 必須由程式補 UNKNOWN

不要讓 LLM 每次自己列完整欄位。

流程：

```text
LLM 抽到：
  floor=3F
  equipment_type=AIR_CONDITIONER
  state=SUSPECTED_ABNORMAL

FrameSchemaRegistry 完成：
  organization=UNKNOWN
  site=UNKNOWN
  building=UNKNOWN
  room=UNKNOWN
  observer=UNKNOWN
  cause=UNKNOWN
  severity=UNKNOWN
  ...
```

因此「欄位完整性」是 deterministic code 責任，不是 prompt 責任。

---

# 14. Context Builder：背景不能全部塞給 LLM

LLM 不負責記住整個世界。

每一次只組受控的 `ContextBundle`。

固定候選來源：

```text
1. nearby evidence
2. quoted / reply evidence
3. sender entity context
4. explicit entity matches
5. active frames involving those entities
6. location hierarchy
7. temporal-nearby frames
8. open slots
9. BM25 / FTS candidates
10. embedding candidates
11. unresolved candidates
12. similar historical corrections
```

Context Bundle 範例：

```yaml
task: RESOLVE_NEW_EVIDENCE
new_evidence: ...
recent_evidence: ...
entities: ...
active_frames: ...
open_slots: ...
candidate_frames: ...
related_evidence: ...
similar_corrections: ...
```

需要明確 context budget；不要用滿模型最大 context。

---

# 15. Retrieval / Resolution Loop

一次 retrieval 不一定正確。

允許受控的多輪：

```text
retrieve
  -> LLM resolve
  -> NEED_MORE_CONTEXT
  -> controller executes search requests
  -> ContextBundle v2
  -> LLM resolve
  -> ATTACH / NEW / UNRESOLVED
```

最多建議 2~3 round。

超過即 `UNRESOLVED`，禁止無限 agent loop。

---

# 16. Candidate Scorer：可微分層的第一個落點

第一版先用人工權重：

```text
Score(evidence, frame) =
    w1 * semantic
  + w2 * entity_overlap
  + w3 * location_overlap
  + w4 * actor_overlap
  + w5 * temporal
  + w6 * open_slot_match
  + w7 * reply_relation
  + w8 * correction_similarity
```

初始優先級可以讓：

```text
reply_relation > entity/open_slot > location > temporal > embedding
```

但所有 feature score 都要保存到 `model_scores`。

之後可無痛替換：

```text
HeuristicCandidateScorer
  -> TorchCandidateScorer
```

Pipeline interface 不變。

重要邊界：

```text
gradient updates model parameters
NOT canonical facts
```

---

# 17. 如何從 correction 形成 learning signal

人工把：

```text
Evidence X -> Frame B
```

改成：

```text
Evidence X -> Frame A
```

自然形成：

```text
positive pair: (X, A)
negative pair: (X, B)
```

之後可訓 ranking / cross-encoder / MLP：

```text
correct frame score up
wrong frame score down
```

第一批值得學習的 module 優先順序：

1. `FrameReranker`
2. `EntityResolver`
3. `ContextRouter`
4. `SlotValueRanker`

Report Generator 不應優先訓練。

---

# 18. Mutation Controller：canonical truth 的唯一寫入口

完整 write path：

```text
LLM proposal
  -> schema validator
  -> provenance validator
  -> temporal validator
  -> contradiction validator
  -> entity type validator
  -> duplicate delta validator
  -> transaction
  -> append slot_delta
  -> update current frame projection
  -> save decision receipt
  -> reindex
```

LLM 不持有 DB write tool。

---

# 19. 主 Pipeline

正式流程固定為：

```text
01 INGEST
02 STORE RAW EVIDENCE
03 EXTRACT ATOMIC FRAMES
04 COMPLETE UNKNOWN SLOTS
05 ENTITY RESOLUTION
06 FRAME CANDIDATE RETRIEVAL
07 CANDIDATE SCORING
08 FRAME RESOLUTION
09 DELTA PROPOSAL
10 VALIDATION
11 COMMIT + DECISION RECEIPT
12 REINDEX
13 ENQUEUE RECONCILIATION
14 EVENT BUILDER
15 REPORT (最後才做)
```

注意：第一版只需要做到 1~13。

---

# 20. 三個自循環

## LOOP 1 — Evidence / World Memory Loop

每筆新 Evidence：

```text
NEW EVIDENCE
 -> EXTRACT
 -> RESOLVE
 -> NEW FACT / CORRECTION / CONTRADICTION / FILL UNKNOWN
 -> PROPOSE MUTATIONS
 -> VALIDATE
 -> COMMIT
 -> REINDEX
```

## LOOP 2 — Memory Reconciliation Loop

只重新檢查受影響範圍：

```text
unresolved references
conflicts
open slots
entity aliases
possible event merge/split
```

新 Evidence 如果補到舊 frame 的未知欄位，就 enqueue 該 frame / entity 的 reconciliation task。

**不要每晚把全部歷史重新丟給 LLM。**

## LOOP 3 — System Evolution Loop

人工 correction / model failures：

```text
corrections
 -> failure clustering
 -> diagnosis
 -> prompt/schema/retrieval/model proposal
 -> historical replay
 -> baseline vs candidate
 -> promote / reject / rollback
```

系統可以自我提出改進，但不能自我竄改 production prompt/schema 後立即生效。

---

# 21. Decision Receipt

每次 LLM 決定都必須保留：

```yaml
decision_id: ...
input_evidence_id: ...
context_bundle_hash: ...
model: ...
model_version: ...
prompt_version: ...
schema_version: ...
retrieval_version: ...
candidates: ...
feature_scores: ...
decision: ATTACH | NEW | UNRESOLVED
mutations: ...
evidence: ...
validator_result: PASS | FAIL
created_at: ...
```

目的：

- 回答「當初為什麼這樣判？」
- 重跑同一決策。
- 比較新版 resolver。
- 產生 training examples。

---

# 22. Event 不要太早建立

只有：

```text
「三樓冷氣好像壞了」
```

時，只建立：

```text
EQUIPMENT_ABNORMALITY Frame
```

之後逐步有：

```text
CONTACT_VENDOR
REPAIR_VISIT
REPAIR_DIAGNOSIS
REPAIR_COMPLETION
```

才由 Event Builder 組成：

```text
EQUIPMENT_REPAIR_INCIDENT
```

因此：

```text
Frame = 世界的最小情境單元
Event = 多個 Frame 後來重建出的較高階事件邊界
Report = Event / Frame 的 narrative view
```

---

# 23. Report 是 view，不是資料來源

Report 可以重新生成。

任何 report claim 都應可以追：

```text
Report Claim
 -> Event / Frame
 -> Slot
 -> Slot Delta
 -> Evidence Record
```

報告可以失敗、重寫、換模型，但不能污染 L0/L1。

---

# 24. Repository / code structure

推薦：

```text
situation_memory/
  domain/
    contracts.py
    frame_schema.py

  sources/
    user_input.py
    line.py
    email.py
    transcript.py
    document.py
    api.py

  llm/
    base.py
    ollama_gateway.py
    openai_compatible_gateway.py

  cognition/
    extractor.py
    entity_resolver.py
    frame_resolver.py
    scorer.py
    delta_proposer.py
    critic.py
    validator.py
    context_builder.py

  memory/
    models.py
    repository.py
    postgres_repository.py
    search_index.py

  pipeline/
    evidence_pipeline.py

  workers/
    reconciliation_worker.py
    evolution_worker.py

  learning/
    dataset_builder.py
    torch_candidate_scorer.py
    evaluator.py

  api/
    app.py
    evidence_routes.py
    frame_routes.py
    correction_routes.py
```

---

# 25. 必須先固定的 Contracts

第一版先定這些版本化 contract：

```text
EvidenceRecordV1
AtomicFrameV1
FrameSlotV1
SlotDeltaProposalV1
ContextBundleV1
ResolutionDecisionV1
DecisionReceiptV1
CorrectionV1
```

契約版本必須寫入 decision receipt，否則之後無法 replay。

---

# 26. 建議 API

最小 internal API：

```text
POST /evidence
GET  /evidence/{id}

GET  /frames/{id}
GET  /frames/{id}/history
GET  /frames/{id}/as-of?time=...

POST /corrections

GET  /unresolved
POST /unresolved/{id}/resolve

POST /replay/decision/{decision_id}
POST /reconcile/{frame_id}
```

LINE / User Input / Email 都只負責形成 `EvidenceRecord` 後呼叫同一個 `POST /evidence` / internal service。

---

# 27. 第一版不要做的事情

V1 明確禁止：

```text
X 直接做 Report Generator 當主功能
X 先上 Neo4j 當 canonical DB
X 讓 LLM 直接寫 DB
X 讓 LLM 自己新增 production schema
X 讓模型 confidence 0.93 直接等於可靠
X 每次把全部歷史 context 塞給 LLM
X 只靠 embedding similarity 判斷同一事件
X UNKNOWN 直接用 null 丟掉語義
X correction 覆寫舊歷史
X gradient 直接改 canonical facts
X 無限 agent loop
```

---

# 28. Implementation Milestones

## M0 — Contract + DB Foundation

完成：

- PostgreSQL migrations
- EvidenceRecordV1
- AtomicFrameV1
- FrameSlotV1
- SlotDeltaV1
- DecisionReceiptV1
- FrameSchemaRegistry
- UNKNOWN semantics tests

驗收：

- Evidence append-only。
- Frame schema 可 deterministic 補全 UNKNOWN slots。
- Delta 可以 replay 重建 frame state。

## M1 — Local LLM Extraction

完成：

- StructuredLLM interface
- Ollama adapter
- Extractor
- JSON Schema / Pydantic strict validation

驗收：

- 一句可拆多 frame。
- 不存在欄位不亂猜。
- 所有結果能追回 evidence_id。

## M2 — Retrieval + Resolver

完成：

- Context Builder
- Candidate Retriever
- heuristic CandidateScorer
- Resolver
- NEED_MORE_CONTEXT 最多 2~3 rounds
- UNRESOLVED

驗收：

- 同主題不同事件可分開。
- 同事件跨時間資訊能 attach。
- 不確定時會 abstain。

## M3 — Mutation Controller

完成：

- Delta proposer
- deterministic validators
- append delta + current projection transaction
- decision receipt

驗收：

- LLM 無直接 DB write path。
- correction 不刪歷史。
- 可重放任意 decision。

## M4 — Reconciliation Loop

完成：

- queue / jobs
- unresolved retry
- conflict retry
- open-slot refill
- entity alias reconciliation
- possible merge/split candidate

驗收：

- 新 evidence 能觸發舊 unresolved 的局部重判。
- 不全庫重跑。

## M5 — Correction + Replay Dataset

完成：

- corrections table
- debug UI/API
- training example builder
- historical replay evaluator

驗收：

- 每個人工修正都形成可學習 positive/negative pair。

## M6 — Differentiable Scorer

完成：

- TorchCandidateScorer
- baseline vs candidate evaluator
- model versioning
- shadow mode

驗收：

- false merge 不可惡化。
- candidate 必須在 replay 上勝過 baseline 才能 promote。

## M7 — Event + Report

最後才做：

- Event Builder
- as-of reconstruction
- evidence-grounded report

---

# 29. 核心測試案例

至少建立以下 golden cases：

## Case A：跨時間補欄位

```text
三樓冷氣好像壞了
A棟那台今天修好了，3500
```

應補：building、repair_state、cost；未知 room 仍保持 UNKNOWN。

## Case B：同設備不同故障事件

```text
8/3 三樓冷氣壞掉
8/5 修好
8/25 三樓冷氣又壞掉
```

不得全部 merge 成同一 incident。

## Case C：錯誤診斷被更正

```text
可能是壓縮機
不是壓縮機，是控制板
```

舊 claim 必須保留並 SUPERSEDED / CORRECTED。

## Case D：後來才知道更早發生的事

valid_time 與 known_time 必須分開；as-of 查詢不得 future leak。

## Case E：一句包含多事件

```text
三樓冷氣修好了，3500；另外明天勤務改 8 點。
```

至少拆兩個 frame。

## Case F：模糊指涉

```text
「那台修好了」
```

候選不足時必須 AMBIGUOUS / UNRESOLVED，不能硬猜。

## Case G：使用者直接輸入

USER_INPUT 與 LINE 走同一 pipeline，但 provenance source_type 必須不同。

---

# 30. 評估指標

不要只看「摘要看起來不錯」。

至少：

```text
Event / Frame Assignment Precision
False Merge Rate
False Split Rate
Entity Resolution Accuracy
Slot Accuracy
Temporal Accuracy
Correction Accuracy
UNKNOWN Precision
UNKNOWN Recall
Abstention Quality
Report Evidence Coverage
```

優先級：

```text
false merge cost > temporary false split cost
```

原因：錯 merge 會污染後續狀態與報告；split 仍可在新證據出現後 merge。

---

# 31. 最高不變量（Hard Invariants）

任何實作都不得違反：

```text
1. Raw Evidence append-only.
2. LLM cannot mutate canonical storage directly.
3. Every committed slot change must have provenance.
4. Unknown is explicit state, not missing implementation.
5. valid_time and known_time are distinct.
6. Corrections append; history is not overwritten.
7. Report is derived view, never canonical source.
8. Model confidence is not authorization to commit.
9. Differentiable parameters may change ranking, not historical truth.
10. Every cognitive decision must be replayable.
11. Context retrieval must be bounded.
12. Resolver must be allowed to abstain.
13. Schema evolution requires versioning + replay validation.
14. Production self-evolution requires baseline comparison and rollback.
```

---

# 32. 給本地 Coding LLM 的執行指令

閱讀本文件後，不要直接做 Event Report UI。

執行順序：

```text
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7
```

每完成一個 milestone：

1. 補 migration / code / tests。
2. 執行該 milestone 的 golden tests。
3. 留下測試結果。
4. 不得因為後續功能方便而破壞 Hard Invariants。
5. 不得把 LLM inference 寫成 canonical fact，除非標記為 INFERRED 並帶 provenance。
6. 若 schema 需要新增欄位或 frame type，先提出 versioned schema proposal，不直接偷偷改既有定義。

第一個真正可用的完成點是 **M4**：此時系統已能持續吃 Evidence、重建 frame、補 slot、保存 delta、局部 reconciliation。

M5/M6 才開始讓它「越用越準」。

M7 才開始把這些可追溯事實寫成報告。

---

# 33. 一句話定位

這個專案不是 LINE Summarizer。

它是：

> **Differentiable Temporal Situation Memory — 用不可變 Evidence 與 Slot Delta 保存世界變化，用受控 LLM 與可微分 Resolver 處理不確定性，用 Correction + Replay 讓系統逐步改善，最後才從可回放的世界狀態生成論述。**
