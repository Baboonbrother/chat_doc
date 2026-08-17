# chat_doc — Local Agent Handoff

## Architecture references

### Differentiable Temporal Situation Memory

For the source-agnostic fragmented-information / world-state memory system, read:

1. `DIFFERENTIABLE_TEMPORAL_SITUATION_MEMORY_V1.md`

This document is the implementation baseline for:

- Evidence sources beyond LINE, including direct user input, documents, transcripts, APIs, and other adapters.
- Atomic Situation Frames with explicit WHO / WHAT / WHEN / WHERE / OBJECT slots.
- Explicit UNKNOWN / AMBIGUOUS / CONFLICTING semantics.
- Append-only Slot Delta history and bitemporal reconstruction.
- Entity / Frame resolution, bounded Context Bundles, and local LLM structured-output gateways.
- Reconciliation loops, correction memory, decision receipts, replay, and controlled self-evolution.
- A differentiable candidate scorer / reranker that learns from corrections without mutating canonical facts.
- Milestones M0 through M7 and the hard invariants that local coding agents must preserve.

Do **not** begin with the report generator. Implement the milestones in the order defined by the design document.

---

## Current task: DeepSeek V4 Flash on R9700 32GB + 64GB RAM

Local coding agents must read these files in this order:

1. `DEEPSEEK_V4_R9700_64GB_SAFE_MODE.md`
2. `DEEPSEEK_V4_R9700_64GB_RUNBOOK.md`

### Priority rule

`DEEPSEEK_V4_R9700_64GB_SAFE_MODE.md` **overrides** any performance-oriented tuning in the older runbook.

User preference is explicit:

> Protect system stability even if inference becomes much slower.

Default operating policy:

- start at `ctx=2048`
- start with `8GB` expert cache
- move to `12GB` only after stable validation
- `16GB` is optional
- do **not** automatically test `24GB / 28GB / 32GB` expert caches
- keep substantial RAM and VRAM headroom
- use SSD streaming rather than forcing model residency
- stop on sustained memory pressure or swap growth
- implement a PID-targeted memory watchdog before long runs

A stable 1–3 tok/s result is preferable to a faster configuration that risks OOM, GPU reset, desktop freeze, or swap thrashing.

The local agent should produce `~/deepseek-r9700/RESULT.md` with both performance and safety metrics.
