# chat_doc — Local Agent Handoff

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
