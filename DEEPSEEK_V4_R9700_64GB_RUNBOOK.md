# DeepSeek V4 Flash on Radeon AI PRO R9700 32GB + 64GB RAM

Updated: 2026-08-08

## Mission

Get **DeepSeek V4 Flash** producing correct local inference on this host:

- GPU: AMD Radeon AI PRO R9700, 32GB VRAM, RDNA4 `gfx1201`
- System RAM: 64GB
- Storage: assume fast NVMe; verify before downloading model
- OS: Linux preferred

The goal is **correct output first**, then speed. Do not assume the full model can reside in VRAM+RAM.

## Important capacity fact

The most interesting low-bit DeepSeek V4 Flash build for DS4 is currently:

`antirez/deepseek-v4-gguf/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf`

Remote file size: about **86.7GB**.

32GB VRAM + 64GB RAM is only 96GB nominal, and the runtime still needs memory for non-routed weights, KV cache, graph scratch, activations, OS, drivers, buffers, and expert cache. Therefore do **not** design around full residency.

Primary research direction: **SSD streaming / routed expert cache / partial residency**.

## Upstream evidence to verify before doing anything

### 1. Lucebox

Repo: https://github.com/Luce-Org/lucebox

Current README states:

- `DeepSeek V4 Flash ROCMFPX HIP` is supported.
- Radeon AI PRO R9700 (`gfx1201`) is a tested target.
- Minimum listed ROCm for R9700 is ROCm 6.4+.
- Their R9700 HIP benchmark is listed at about 55 tok/s for the tested optimization path.

This proves that **R9700/gfx1201 HIP kernels can work well**. It does **not** prove our 32GB+64GB machine can fully resident-load a DeepSeek V4 Flash quant.

### 2. DwarfStar / DS4

Repo: https://github.com/antirez/ds4

DS4 is a narrow native inference engine designed first for DeepSeek V4 Flash.

Current main README says:

- DeepSeek V4 Flash SSD streaming is supported on Metal.
- ROCm is officially used on Strix Halo.
- ROCm SSD streaming on main is explicitly described for GLM 5.2.
- SSD streaming works by keeping non-routed weights resident while routed MoE experts live in a dynamic in-memory cache and are loaded from GGUF on cache misses.
- Example 64GB-machine expert cache budget: `--ssd-streaming-cache-experts 32GB` on the Metal path.

So: **do not assume DeepSeek V4 Flash SSD streaming on R9700 ROCm is already fully merged/stable**.

### 3. DS4 R9700 / ROCm PRs

At the time this document was written, inspect at least these PRs:

- https://github.com/antirez/ds4/pull/599
  - `rocm: fix build on gfx1201 (RDNA4, R9700) — gate the WMMA v1 kernel`
- https://github.com/antirez/ds4/pull/623
  - `ROCm: restore DeepSeek V4 Flash decode performance and Q4 SSD streaming`

These were still open when checked on 2026-08-08. Their status may change. Never blindly cherry-pick old commits after they merge or get superseded.

### 4. Model

Hugging Face:

https://huggingface.co/antirez/deepseek-v4-gguf

Preferred first candidate:

`DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf`

Known remote size at the time of writing: about 86.7GB.

## Local LLM operating rules

You are the implementation agent on the actual R9700 host. Do not merely explain commands. Execute, inspect output, record evidence, and adapt.

Rules:

1. Never erase working ROCm drivers without first recording the current working state.
2. Never change ROCm versions just because a README says `6.4+`. First inspect current version and test it.
3. Never download an 86.7GB model until free NVMe space is verified. Keep at least roughly 120GB free for model + temporary/build/cache overhead; more is preferred.
4. Do not fill the OS filesystem with the model if a dedicated NVMe data volume exists.
5. Start with `ctx=4096` until correctness is proven.
6. Do not optimize token/s until a deterministic smoke prompt returns correct text repeatedly.
7. Record exact git commit SHAs, ROCm version, kernel version, GPU detection, command line, RAM, VRAM, and speed.
8. If an upstream PR is required, inspect its diff and current merge state before applying it.
9. Prefer reversible branches/worktrees over editing upstream source in place.
10. Do not use undocumented `HSA_OVERRIDE_GFX_VERSION` hacks unless the native `gfx1201` build has failed and the failure is documented.

---

# Phase 0 — Inventory the machine

Create a log directory:

```bash
mkdir -p ~/deepseek-r9700/logs
```

Capture baseline:

```bash
{
  date -Is
  uname -a
  cat /etc/os-release
  lspci -nn | grep -Ei 'VGA|Display|AMD'
  free -h
  df -hT
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL
  rocminfo 2>&1 | head -n 120
  rocm-smi 2>&1
  hipcc --version 2>&1
} | tee ~/deepseek-r9700/logs/00_host_inventory.txt
```

Success criteria:

- R9700 is visible.
- `gfx1201` is visible in ROCm/HIP tooling.
- VRAM is approximately 32GB.
- system RAM is approximately 64GB.
- identify the NVMe target and its free space.

If `rocminfo`/`rocm-smi` do not work, stop DeepSeek work and repair the ROCm baseline first.

---

# Phase 1 — Prove R9700 ROCm works with a smaller model

Before debugging DeepSeek V4, isolate hardware/runtime support with a smaller, known model.

Preferred route: current `llama.cpp` ROCm build or Lucebox ROCm image/build.

For llama.cpp, build natively for the R9700 rather than relying on an old generic binary:

```bash
cd ~/deepseek-r9700
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
git rev-parse HEAD | tee ../logs/01_llamacpp_commit.txt
cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
```

Run a small non-MoE model that fits comfortably in VRAM. Use context 4096.

Record the complete command and output.

Success criteria:

- model loads on HIP
- prompt evaluates
- output is coherent
- no segfault at first token

Do not proceed until this passes, otherwise every later failure is ambiguous.

---

# Phase 2 — Establish Lucebox as the R9700 reference path

Clone and inspect current docs rather than assuming the commands in this runbook are timeless:

```bash
cd ~/deepseek-r9700
git clone --recursive https://github.com/Luce-Org/lucebox.git
cd lucebox
git rev-parse HEAD | tee ../logs/02_lucebox_commit.txt
```

Read:

- `README.md`
- `Dockerfile.rocm`
- R9700 / HIP quick-start files linked by README
- DeepSeek V4 Flash ROCMFPX implementation notes

First test Lucebox with a model that fits in 32GB VRAM. The purpose of this phase is not yet to fit the 86GB+ DeepSeek model; it is to prove Lucebox's `gfx1201` HIP path works on this exact host.

Record:

- compile/container path
- detected architecture
- token/s
- VRAM use
- correctness

If Lucebox works but DS4 later fails, treat DS4 ROCm support as the likely variable rather than the GPU/driver baseline.

---

# Phase 3 — Inspect DS4 upstream state before selecting a branch

```bash
cd ~/deepseek-r9700
git clone https://github.com/antirez/ds4.git
cd ds4
git rev-parse HEAD | tee ../logs/03_ds4_main_commit.txt
```

If GitHub CLI is available:

```bash
gh pr view 599 --repo antirez/ds4 --json number,title,state,mergedAt,headRefName,headRefOid,url
gh pr view 623 --repo antirez/ds4 --json number,title,state,mergedAt,headRefName,headRefOid,url
```

Decision:

### Case A — both relevant changes are merged into main

Use current main and do not cherry-pick.

### Case B — one/both PRs are still open

Inspect the diffs first:

```bash
gh pr diff 599 --repo antirez/ds4 > ../logs/pr599.diff
gh pr diff 623 --repo antirez/ds4 > ../logs/pr623.diff
```

Determine whether #623 includes or depends on #599 and whether later commits supersede them.

Create a local experimental branch. Do not modify `main` directly.

If the PRs are cleanly fetchable and still applicable, use a reversible branch/worktree. Record every applied SHA.

### Case C — PRs closed unmerged / superseded

Find the replacement commit/PR/issue and document the lineage. Do not force old patches onto new main.

---

# Phase 4 — Build DS4 ROCm for gfx1201

Current upstream exposes a `make strix-halo` ROCm target, but R9700 is **RDNA4 gfx1201**, not Strix Halo.

Before compiling, inspect:

```bash
grep -nE 'strix|rocm|gfx11|gfx12|AMDGPU|HIP' Makefile rocm/* ds4_rocm* 2>/dev/null
```

The implementation agent must determine from current source/PR #599 whether:

- `make strix-halo` is intentionally reusable for gfx1201, or
- a new R9700/gfx1201 target/flag is required.

Do not hard-code `gfx1151` for an R9700.

Compile with the source-supported native `gfx1201` path.

Record build command and compiler output in:

`~/deepseek-r9700/logs/04_ds4_build.txt`

Success criteria:

- no architecture fallback to the wrong GPU family
- no WMMA-v1 compile failure
- `./ds4 --help` works
- ROCm backend can initialize

---

# Phase 5 — Download the lowest-memory DeepSeek V4 Flash candidate

Only after capacity checks pass.

Preferred first model:

```text
antirez/deepseek-v4-gguf
DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf
```

Use `hf download` or DS4's current `download_model.sh` alias if the current README maps `ds4f-q2` to this exact/current checkpoint.

Example with HF CLI:

```bash
mkdir -p /PATH/ON/FAST/NVME/deepseek-v4
hf download antirez/deepseek-v4-gguf \
  DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf \
  --local-dir /PATH/ON/FAST/NVME/deepseek-v4
```

After download:

```bash
ls -lh /PATH/ON/FAST/NVME/deepseek-v4/*.gguf
```

Verify checksum against Hugging Face metadata before blaming inference code for corruption.

---

# Phase 6 — First DS4 DeepSeek smoke test

Critical constraint: as of this runbook, DS4 main documents DeepSeek Flash SSD streaming primarily on Metal, while ROCm SSD streaming is explicitly documented for GLM 5.2. R9700 DeepSeek Flash streaming should therefore be treated as **experimental until the relevant ROCm work is verified/merged**.

Start extremely small:

- context: 4096
- thinking off
- token limit: tiny
- deterministic prompt

Target prompt:

```text
Reply with exactly: OK
```

If the selected branch actually supports DeepSeek Flash ROCm SSD streaming, start with a conservative expert cache rather than trying to consume all 64GB RAM.

Candidate shape, only if current `./ds4 --help` confirms these flags for the ROCm DeepSeek path:

```bash
./ds4 --rocm \
  -m /PATH/ON/FAST/NVME/deepseek-v4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf \
  --ssd-streaming \
  --ssd-streaming-cache-experts 24GB \
  --ctx 4096 \
  --nothink \
  --tokens 8 \
  -p 'Reply with exactly: OK'
```

Why start at 24GB rather than 32GB: this machine has only 64GB system RAM and a discrete 32GB GPU. Leave room for resident non-routed tensors, host buffers, page cache, runtime, OS, KV/graph allocations, and ROCm behavior. Increase cache only after measuring actual headroom.

If 24GB fails due to capacity, try smaller cache budgets such as 16GB. If it succeeds and the host remains healthy, test 28GB/32GB and benchmark misses/token/s.

Record during the run:

```bash
watch -n 0.5 'free -h; echo; rocm-smi --showmeminfo vram --showuse 2>/dev/null'
```

Also capture `iostat -xz 1` if available to verify SSD streaming activity.

---

# Phase 7 — Failure classification

Do not randomly change five variables at once.

## A. Compile failure mentions WMMA/gfx1201

Likely DS4 RDNA4 build support. Compare against PR #599/current equivalent.

## B. ROCm initializes but first token crashes

Reduce to:

- `ctx=4096`
- no speculative decoder
- no exotic KV quant
- one GPU
- simplest supported Flash execution path

Compare with the already-proven Lucebox/llama.cpp R9700 baseline.

## C. OOM / system begins swapping heavily

Reduce expert cache. Do not enable huge swap as the first fix: that can convert a clear capacity failure into unusable disk thrashing.

## D. Correct output but extremely slow

Measure:

- expert-cache hit rate if DS4 reports it
- NVMe read throughput / latency
- CPU utilization
- GPU utilization
- prefill vs decode separately

Then tune cache size.

## E. Gibberish / confident wrong text

Treat as correctness failure, not performance. Verify:

- exact GGUF checksum
- current supported DeepSeek checkpoint
- prompt template
- branch compatibility
- KV cache type

Recent llama.cpp DeepSeek V4 work has had correctness bugs with quantized K-cache. For initial validation, prefer conservative/full-precision cache behavior where supported rather than maximizing memory savings immediately.

---

# Phase 8 — Benchmark matrix after correctness

Once `OK` smoke tests are repeatable, run a small matrix:

| Test | ctx | expert cache | SSD streaming | Record |
|---|---:|---:|---|---|
| A | 4096 | 16GB | yes | correctness, tok/s, RAM, VRAM |
| B | 4096 | 24GB | yes | same |
| C | 4096 | 28GB | yes | same |
| D | 4096 | 32GB | yes | same, only if safe |
| E | 8192 | best safe cache | yes | same |

Stop any configuration that causes sustained host memory pressure or pathological swapping.

The winning configuration is not necessarily the largest cache. It is the largest **stable working set** with useful expert hit rate and no OS thrash.

---

# Phase 9 — Produce a final machine report

Create:

`~/deepseek-r9700/RESULT.md`

Required fields:

```text
GPU:
GPU arch:
VRAM:
RAM:
CPU:
OS:
Kernel:
ROCm:
NVMe model:
NVMe mount/filesystem:
llama.cpp commit:
Lucebox commit:
DS4 commit/branch:
Applied PR/commit SHAs:
Model filename:
Model SHA256:
Model size:
Command that first produced correct output:
Context:
Expert cache:
Peak system RAM:
Peak VRAM:
SSD read throughput:
Prefill tok/s:
Decode tok/s:
Correctness smoke test result:
Known failures:
Recommended next step:
```

Commit `RESULT.md` plus any scripts/config needed to reproduce the successful run to the user's own working repo.

---

# Recommended execution priority

1. **Do not download first.** Inventory host and storage.
2. Prove native `gfx1201` ROCm with a smaller model.
3. Prove Lucebox R9700 HIP path.
4. Inspect current DS4 main + PR #599 + PR #623 state.
5. Build the correct R9700 DS4 ROCm branch.
6. Download the 86.7GB IQ2XXS imatrix DeepSeek V4 Flash quant to fast NVMe.
7. Attempt a tiny 4096-context correctness smoke test with conservative expert cache.
8. Only after correct output, tune cache and benchmark.

## Expected outcome

The hardware is capable of useful ROCm inference, but **DeepSeek V4 Flash on a discrete R9700 32GB + only 64GB system RAM is a capacity-edge, software-edge configuration**. The plausible route is not full residency; it is MoE-aware SSD streaming / expert caching. Current upstream evidence makes this worth testing, but it should be treated as an engineering experiment until a repeatable R9700 ROCm DeepSeek Flash streaming run is demonstrated on this exact host.
