# DeepSeek V4 Flash — R9700 32GB + 64GB RAM SAFE MODE

Updated: 2026-08-08

This document OVERRIDES the performance-oriented cache tuning in `DEEPSEEK_V4_R9700_64GB_RUNBOOK.md`.

## User priority

The user explicitly prefers:

> **Slower token generation is acceptable. System stability is more important than speed. Do not push RAM/VRAM close to capacity.**

The implementation agent MUST optimize for **no crash, no desktop freeze, no OOM, no sustained swap thrash** before token/s.

---

# 1. Safety policy

Treat this machine as a stability-constrained host:

- GPU: AMD Radeon AI PRO R9700, 32GB VRAM
- RAM: 64GB
- Large model: DeepSeek V4 Flash low-bit GGUF, ~86.7GB candidate
- Main strategy: SSD streaming / partial residency

Do NOT try to make 32GB VRAM + 64GB RAM behave like a 96GB unified-memory machine. They are different memory pools and both require headroom.

## Default headroom targets

During normal inference, aim to keep:

- **System MemAvailable >= 12GB**
- Prefer **MemAvailable >= 16GB** during first validation runs
- **Swap used <= 1GB** ideally
- Abort if swap use is continuously increasing or disk latency becomes pathological
- **VRAM use <= about 26GB** during first stable configuration
- Prefer leaving **4–6GB VRAM free** for ROCm/runtime transient allocations

These are conservative operating targets, not claims about absolute hardware limits.

## Hard stop conditions

Immediately terminate the inference process if ANY of these occur:

1. `MemAvailable < 8GB` for more than ~10 seconds.
2. Swap exceeds ~2GB AND continues increasing.
3. The desktop becomes visibly unresponsive or SSH latency rises sharply.
4. Kernel logs show OOM killer activity.
5. VRAM allocation repeatedly approaches the full 32GB and ROCm starts allocation failures.
6. NVMe is at 100% utilization with very high latency for a sustained period and the machine becomes unresponsive.
7. Temperature/power behavior is abnormal for the host.

After a safety stop, reduce memory pressure before retrying. Do not simply rerun the same configuration.

---

# 2. Stable-first default configuration

For the FIRST DeepSeek V4 Flash test, use the smallest practical working set.

Preferred starting point:

- context: **2048**
- expert cache: **8GB**
- output tokens: 8–16
- thinking: off
- SSD streaming: on
- one inference process only
- no parallel requests
- no speculative decoding
- no large batch/prefill experiments
- no KV-cache quantization experiments until correctness is proven

If current DS4 build supports the required flags, the command shape should resemble:

```bash
./ds4 --rocm \
  -m /PATH/ON/FAST/NVME/deepseek-v4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf \
  --ssd-streaming \
  --ssd-streaming-cache-experts 8GB \
  --ctx 2048 \
  --nothink \
  --tokens 16 \
  -p 'Reply with exactly: OK'
```

IMPORTANT: confirm flag names using the current `./ds4 --help`. Do not blindly assume this exact CLI is current.

---

# 3. Cache policy

The old performance sweep `16GB -> 24GB -> 28GB -> 32GB` is NOT the default anymore.

Use this stability ladder instead:

| Stage | Expert cache | Purpose |
|---|---:|---|
| S0 | 8GB | First safe boot / correctness |
| S1 | 12GB | Default target if S0 is stable |
| S2 | 16GB | Optional only after long stable run |
| S3 | >16GB | DO NOT test unless the user explicitly asks to trade headroom for speed |

The preferred long-term operating point is **8–12GB**, even if token/s is substantially slower.

Do not automatically increase cache because RAM appears unused once. Linux page cache, ROCm allocations, model metadata, temporary buffers and workload spikes can change pressure during longer prompts.

---

# 4. Context policy

Use:

1. `ctx=2048` for first validation.
2. `ctx=4096` only after repeated stable runs.
3. Do NOT test 8192+ merely for benchmarking.
4. Increase context only when there is a real usage need.

Long context is a capacity feature, not a goal by itself.

---

# 5. Monitoring is mandatory

Before launching the model, open a second terminal or tmux pane.

## Host memory

```bash
watch -n 1 'free -h'
```

Pay attention to **available**, not only `free`.

## GPU

```bash
watch -n 1 'rocm-smi --showmeminfo vram --showuse 2>/dev/null'
```

## NVMe

If `iostat` exists:

```bash
iostat -xz 1
```

## OOM / kernel

In another terminal:

```bash
sudo dmesg -wT | grep -Ei 'oom|out of memory|amdgpu|xgmi|gpu reset|fault'
```

If root access is not desired, use:

```bash
journalctl -kf | grep -Ei 'oom|out of memory|amdgpu|gpu reset|fault'
```

---

# 6. Add a watchdog instead of trusting the model process

The implementation agent should create a small watchdog script before long tests.

Minimum behavior:

- poll `/proc/meminfo`
- watch `MemAvailable`
- watch swap usage
- record timestamped samples
- if the hard-stop threshold is crossed, send SIGTERM to the inference PID
- wait several seconds
- if it does not exit, send SIGKILL

Do not kill unrelated processes. The watchdog must receive the exact inference PID.

Suggested policy:

```text
WARN: MemAvailable < 12GB
STOP: MemAvailable < 8GB for 10 seconds
WARN: swap > 1GB
STOP: swap > 2GB and rising across consecutive samples
```

This watchdog is more important than squeezing out an additional token/s.

---

# 7. Do not use giant swap as a capacity hack

A small normal swap area is acceptable as an emergency buffer.

Do NOT solve model capacity by creating 64–128GB of swap and allowing the host to page indefinitely.

Reason:

- it can hide real memory exhaustion
- it can make the desktop appear frozen
- random expert access plus VM paging can create pathological I/O contention
- recovery becomes difficult when both model streaming and OS paging fight for the same NVMe

SSD streaming should be controlled by the inference engine, not accidentally delegated to the Linux swap subsystem.

---

# 8. Slow is a successful result

For this machine, success is NOT defined by token/s.

A configuration is successful if:

- DeepSeek V4 Flash produces coherent output repeatedly
- no OOM killer
- no GPU reset
- no desktop freeze
- no sustained swap growth
- system remains interactively usable
- model can be stopped cleanly

Even **1–3 tok/s** can be considered a better result than a 6–10 tok/s configuration that puts the host close to failure.

Do not reject a stable configuration only because it is slow.

---

# 9. Stable benchmark protocol

After the `OK` smoke test works, use only this matrix by default:

| Test | ctx | expert cache | Run length |
|---|---:|---:|---|
| A | 2048 | 8GB | short smoke |
| B | 2048 | 12GB | short smoke |
| C | 4096 | 12GB | short smoke |
| D | 4096 | 12GB | 10–15 min stability run |
| E | 4096 | 16GB | OPTIONAL, only if D has large headroom |

Do NOT benchmark 24/28/32GB caches automatically.

For every test record:

- `MemAvailable` minimum
- peak swap usage
- peak VRAM
- average NVMe utilization and latency
- GPU utilization
- prompt processing tok/s
- decode tok/s
- output correctness
- whether desktop/SSH stayed responsive

---

# 10. Configuration selection rule

Choose the **smallest cache that gives acceptable usability**.

Example decision:

```text
8GB cache  -> 2.0 tok/s, very stable
12GB cache -> 2.8 tok/s, very stable
16GB cache -> 3.2 tok/s, RAM headroom noticeably reduced

Winner: 12GB
```

Do NOT choose 16GB merely because it is faster.

A 10–20% speed gain is not worth materially reducing safety headroom.

---

# 11. RESULT.md must report safety, not just speed

Add these fields to the final `~/deepseek-r9700/RESULT.md`:

```text
Selected SAFE configuration:
Context:
Expert cache:
Decode tok/s:
Prompt tok/s:
Minimum MemAvailable observed:
Peak RAM used:
Peak swap used:
Peak VRAM used:
Peak NVMe utilization:
Peak NVMe await/latency:
GPU reset observed: YES/NO
OOM observed: YES/NO
Desktop/SSH remained responsive: YES/NO
Longest stable run:
Reason this configuration was selected:
```

The final recommendation must prioritize stability over benchmark speed.

---

# 12. Instruction to the local coding agent

When you read this file, do not ask the user whether to maximize performance. The preference is already decided:

> **Protect the machine. Accept slow inference.**

Start with 8GB cache and ctx 2048. Establish correctness and system stability. Move to 12GB only if safe. Treat 16GB as optional. Do not exceed 16GB expert cache unless the user later gives explicit permission.

If the model cannot operate under these conservative limits, report that clearly instead of forcing the host into memory pressure.
