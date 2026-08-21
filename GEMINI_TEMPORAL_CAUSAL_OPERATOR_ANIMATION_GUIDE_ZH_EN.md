# Gemini 教學動畫任務：時間因果機制算子 / Temporal Causal Mechanism Operator

> **公開文件 / PUBLIC DOCUMENT**
>
> 目的：請 Gemini 依照本文件，製作一個能讓一般使用者理解「為什麼節點之間不能只用單點數學函數，而應該升級為 Temporal Causal Mechanism Operator」的互動式教學動畫。
>
> 本文件只包含公開可理解的抽象方法與航運示例，不依賴任何私有 repository、策略、資料或內部研究結果。

---

# 0. 你要交付什麼 / Deliverable

請做成一個 **可直接在瀏覽器開啟的互動式教學動畫**。

建議交付：

```text
animation/
  index.html
  app.js
  styles.css
  README.md
```

如果可以單檔完成，也可輸出：

```text
temporal_causal_operator_demo.html
```

要求：

- 不需要後端。
- 不需要 API key。
- 不需要資料庫。
- 可用純 HTML/CSS/JS 或 React/Vite，但必須有清楚 run instructions。
- 桌面優先，手機可閱讀。
- 中文優先，保留必要英文術語。
- 16:9 主畫布最佳化。
- 動畫不能只播放影片；使用者必須可以 Pause / Previous / Next / Restart。

---

# 1. 教學目標 / Learning Goal

使用者看完後必須能回答：

1. Node 是什麼？
2. 為什麼 Node 應該表示一條 time series / temporal process？
3. 為什麼普通 `Y_t=f(X_t)` 不足以表示很多真實世界機制？
4. Temporal Causal Mechanism Operator 是什麼？
5. distributed lag、memory、feedback、regime、stochasticity 各自解決什麼？
6. 為什麼 mathematical function 仍然重要，但只是 operator backend 之一？
7. intervention / counterfactual 為什麼是 causal system 的必要能力？
8. 為什麼不能把 evidence quality、mechanism strength、edge existence 混成同一個 weight？

---

# 2. 核心概念 / Canonical Concept

錯誤但簡單的起點：

```math
Y_t=f(X_{t-1})
```

升級後：

```math
X_v(t)
=
\mathcal M_v\Big(
\{X_u[0:t)\}_{u\in Pa_t(v)},
U_v[0:t),
C[0:t);
\theta_v(t)
\Big)
```

用白話表示：

```text
一個 target node 的現在
不是只由另一個 node 的上一個值決定，
而可能由：

- 多個 parent 的整段歷史
- 延遲傳導
- 累積狀態
- regime/context
- 未觀測衝擊
- feedback
- 隨時間改變的參數

一起決定。
```

請把這個概念做成動畫，不要只把公式貼在畫面上。

---

# 3. 全片視覺語言 / Visual Grammar

請使用一致的視覺語意：

```text
圓角卡片 = Node
箭頭 = Mechanism connection
中間機制盒 = MechanismOperator
小折線 = Node trajectory
帶狀區間 = uncertainty
虛線 = latent / hypothetical
實線 = observed
環狀箭頭 = feedback
水平延遲帶 = lag/kernel
多層透明卡片 = regime mixture
```

不要使用：

- 大量裝飾 icon 取代語義。
- 每個場景換一種完全不同的配色規則。
- 只靠顏色表示重要狀態，需搭配 label/badge。
- 過度華麗 particle effect。

核心目標是「看懂機制」，不是做廣告影片。

---

# 4. Storyboard / 分鏡

整體建議 8–10 個 scenes。

---

## Scene 1 — 所有節點都有時間 / Every node lives in time

畫面先出現三個 node：

```text
Freight Price
Port Congestion
Fleet Capacity
```

每個 node 內不是一個數字，而是一條 mini line chart。

旁白：

> 我們不是在連接三個數字。我們真正處理的是三條隨時間演化的過程。

動畫：

- 時間游標從左往右移。
- 三條線以不同速度變動。
- 標註 `daily / weekly / yearly`，強調 mixed time scale。

必要 takeaway：

```text
NODE = TEMPORAL PROCESS
```

---

## Scene 2 — 普通 function edge 的限制

顯示：

```text
Congestion(t-1)
      ↓
    f(x)
      ↓
Freight Price(t)
```

旁邊顯示公式：

```math
Y_t=f(X_{t-1})
```

然後依序出現紅色問題標記：

```text
What about 30-day history?
What about capacity?
What about feedback?
What about regime change?
What about irregular observations?
```

動畫必須明確讓使用者看到：一個 scalar-to-scalar function 無法自然表達這些問題。

不要說「數學函數是錯的」。正確說法：

> 這個 abstraction 太窄。

---

## Scene 3 — Function 升級成 Operator

把原本小小的 `f(x)` 方框展開成大一點的 `MechanismOperator`。

輸入改成：

```text
Congestion history ─┐
Capacity history ───┼─> [ MechanismOperator ] ─> Freight Price trajectory
Demand history ─────┤
Regime/context ─────┘
```

畫面出現：

```text
trajectory → trajectory
function space → function space
```

旁白：

> Operator 不只看一個點。它可以讀一段歷史，再輸出一段新的時間軌跡。

核心 takeaway：

```text
EDGE / MECHANISM = TEMPORAL CAUSAL OPERATOR
```

---

## Scene 4 — 一個 Operator 可以有不同 backend

MechanismOperator 打開成抽屜/選單：

```text
HARD_EQUATION
SYMBOLIC_FUNCTION
DISTRIBUTED_LAG
STATE_SPACE
NEURAL_ODE
NEURAL_CDE
NEURAL_SDE
NEURAL_OPERATOR
REGIME_MIXTURE
EVENT_OPERATOR
HYBRID
```

不要一次全部大量解釋。

請分三群動畫：

### Known mechanism

```text
HARD_EQUATION
SYMBOLIC_FUNCTION
DISTRIBUTED_LAG
```

### Hidden/continuous dynamics

```text
STATE_SPACE
NEURAL_ODE/CDE/SDE
```

### Flexible trajectory mechanisms

```text
NEURAL_OPERATOR
REGIME_MIXTURE
HYBRID
```

旁白：

> Mathematical function 沒有被拿掉；它只是 MechanismOperator 的一種 backend。

---

## Scene 5 — 航運慢結構：多年熊市到船隊容量

這是主要公開例子。

流程：

```text
多年低報酬 / Shipping capital depression
        ↓
Newbuilding appetite
        ↓
Newbuilding orders
        ↓
Distributed lag 24–48 months
        ↓
Ship deliveries
        ↓
Fleet capacity
        ↓
Capacity buffer
```

視覺重點：

- 左側慢速 timeline 以「年」為刻度。
- `Orders → Deliveries` 中間不是普通箭頭，而是一個寬的 lag kernel。
- kernel 動畫讓不同歷史 orders 逐步影響未來 deliveries。

公式可以出現，但只當輔助：

```math
Deliveries_t=\sum_{\tau}K(\tau)Orders_{t-\tau}
```

旁白要強調：

> 這不是「今年少訂船，明天就少一艘船」。真正機制是一段分布式時間傳導。

---

## Scene 6 — 快衝擊 × 慢脆弱度

畫面分成兩條 lane：

```text
SLOW STRUCTURE                       FAST SHOCK

Low capital investment              Lockdown/Event
       ↓                                  ↓
Low capacity buffer                 Goods demand shock
       └──────────────┬───────────────────┘
                      ↓
               Capacity pressure
                      ↓
                    Queue
```

讓兩條時間尺度在畫面中央匯合。

重點：

```text
Shock alone != Outcome
Outcome depends on structural state
```

可以顯示：

```math
Impact_t = Shock_t \times Fragility_t
```

但隨後顯示更一般形式：

```math
Impact=\mathcal M(Shock,StructuralState,History)
```

---

## Scene 7 — Feedback

建立：

```text
Queue ↑
  ↓
Waiting Time ↑
  ↓
Effective Capacity ↓
  ↓
Pressure ↑
  └───────────────> Queue ↑
```

動畫不要只畫環。

請真的跑兩次：

### Run A
Capacity buffer 高 → shock 被吸收。

### Run B
Capacity buffer 低 → feedback 放大 → queue 爆發。

讓使用者看懂：

> 同一個 demand shock，在不同 structural state 下可以造成完全不同 trajectory。

---

## Scene 8 — Dynamic Graph / Regime Mixture

顯示三個簡化 graph cards：

```text
NORMAL
CAPACITY-CONSTRAINED
DEMAND-SHOCK
```

再顯示時間 `t` 的 mixture weights：

```text
Normal              0.15
Capacity constrained 0.55
Demand shock         0.30
```

動畫把 graph 疊合成當下 effective graph。

數學：

```math
G(t)=\sum_k\pi_k(t)G_k
```

旁白：

> 世界不是永遠用同一張因果圖運作；不同 regime 可以改變哪些機制最重要。

不要宣稱所有 causal graph 都必須用 mixture；這只是可解釋的一種 dynamic graph 表示法。

---

## Scene 9 — 三個不能混在一起的 weight

畫面放三個獨立 slider/bar：

```text
Structure existence      a(t)
Mechanism strength       g(t)
Evidence reliability     q(t)
```

依序展示：

### Case A
資料品質差，但 mechanism 可能仍真實。

### Case B
資料品質很好，但 causal mechanism 很弱。

### Case C
Edge candidate 尚未升格，因此 structure gate 不確定。

旁白：

> 看不到，不等於不存在；資料可信，也不等於因果效果很強。

這一幕是必要場景，不可省略。

---

## Scene 10 — Intervention / Counterfactual

畫面顯示 factual timeline：

```text
Observed world
Lockdown ON
→ Demand Shock
→ Queue
→ Freight Price
```

使用者按：

```text
[ Remove Lockdown ]
```

動畫分岔成：

```text
FACTUAL
vs
COUNTERFACTUAL
```

並畫兩條 trajectory。

顯示：

```math
do(Lockdown=OFF)
```

旁白：

> Causal model 的價值不只是解釋相關性；它應該能清楚定義「如果改變某個原因，後續軌跡會怎麼變」。

同時必須顯示：

```text
Counterfactual is model-dependent
Uncertainty must remain visible
```

---

# 5. 最後總結畫面 / Final Summary

最後畫面不要塞很多段落。

只顯示：

```text
NODE
= temporal process

MECHANISM
= temporal causal operator

FUNCTION
= one operator backend

GRAPH
= explicit, versioned, possibly dynamic

CAUSAL CLAIM
≠ correlation
≠ LLM opinion
≠ training fit alone
```

再放一個完整但簡化的結構：

```text
slow structure
      +
fast shock
      ↓
mechanism operators
      ↓
dynamic trajectory
      ↓
intervention / counterfactual
```

---

# 6. Interaction Requirements

使用者至少可以：

```text
Previous
Next
Pause/Play
Restart
```

建議額外：

```text
[ Beginner ] [ Researcher ]
```

### Beginner mode

- 少公式
- 多動畫與白話
- operator backend 只顯示類型名稱

### Researcher mode

- 顯示 equation
- lag kernel
- dynamic graph weights
- intervention notation
- uncertainty

兩種 mode 使用同一個故事，不准做成兩份互不一致的內容。

---

# 7. Optional Interactive Sandbox

如果時間允許，最後加入 sandbox：

使用者可調：

```text
Capacity Buffer
Demand Shock
Lag Length
Mechanism Strength
```

右側同步更新：

```text
Queue trajectory
Freight Price trajectory
```

要求：

- 這是 illustrative simulation，不是假裝真實歷史。
- 畫面需明確標註 `Illustrative / Conceptual`。
- 不要使用真實公司或投資建議。

---

# 8. Visual Acceptance Criteria

以下每一項都必須成立：

- [ ] Node 主要以「time series card」而非 scalar card 表示。
- [ ] `f(x)` 與 `MechanismOperator` 的差異有動畫轉換。
- [ ] 至少一幕清楚展示 distributed lag kernel。
- [ ] 至少一幕清楚展示 slow × fast interaction。
- [ ] 至少一幕清楚展示 feedback amplification。
- [ ] 至少一幕展示 dynamic/regime graph。
- [ ] `structure / mechanism / evidence` 三種 weight 分開。
- [ ] intervention/counterfactual 不是只有文字，而是真的分岔 trajectory。
- [ ] latent/uncertain 內容不能畫成確定真實值。
- [ ] mathematical function 被描述為 backend，不是被否定。
- [ ] 最後 summary 能在 20 秒內讀完。

---

# 9. Semantic Failure Conditions

出現以下任何情況都算失敗：

1. 把 `Temporal Causal Operator` 說成只是「更大的 neural network」。
2. 宣稱 neural operator 自動等於 causality。
3. 把 Granger/predictive relation 當成已證實 intervention causality。
4. 把 uncertainty 隱藏掉。
5. 把 `evidence reliability` 與 `mechanism strength` 合成同一個 confidence。
6. 把 event 硬畫成精確連續時間序列，卻沒有說是 conceptual transformation。
7. 把所有 graph 畫成固定 DAG，卻又說世界機制會隨 regime 改變。
8. 把公式堆滿畫面，讓動畫失去教學目的。
9. 使用私有 repo、私有策略或私有資料作為動畫內容。

---

# 10. Gemini 最後回報格式

完成後請回報：

```text
1. files created
2. exact run command
3. scene list implemented
4. interactions implemented
5. assumptions/simplifications
6. screenshots or preview method
7. semantic deviations from this specification
```

不要只回答「完成」。

---

# 11. 一句話設計原則

> **不要把因果畫成一堆箭頭；要讓使用者看見一條時間軌跡如何透過機制、延遲、狀態與回饋，生成另一條時間軌跡。**

> **Do not visualize causality as arrows alone; show how one temporal trajectory generates another through mechanisms, delays, state, regime, and feedback.**
