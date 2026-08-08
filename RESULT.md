# DeepSeek V4 Flash (IQ2XXS GGUF 80.76GB) on AMD Radeon AI PRO R9700 (32GB VRAM + 64GB System RAM)
## Safe Mode Runbook Execution & Benchmark Results

**Date**: 2026-08-08  
**Repository Handoff**: `Baboonbrother/chat_doc`  
**Runbook Reference**: `DEEPSEEK_V4_R9700_64GB_SAFE_MODE.md`  
**Engine**: `ds4` (antirez/ds4, branch `r9700-gfx1201-safe`, PR #599 cherry-picked)  
**Execution Strategy**: **Stability Priority Mode (Safe Mode)**

---

### Executive Summary

DeepSeek V4 Flash (80.76 GB IQ2XXS GGUF model) was successfully loaded and executed on the **AMD Radeon AI PRO R9700 (gfx1201, 32GB VRAM + 64GB System RAM)** utilizing `ds4` ROCm SSD Expert Streaming under strict Safe Mode memory control protocols.

- **Smoke Test Verification**: Passed cleanly (`OK` generated at 8.18 tok/s).
- **Target Safe Configuration (S1: 12GB Cache, ctx 2048/4096)** achieved **5.79 – 5.89 tok/s** decode throughput.
- **System Memory Safety**: Maintain `MemAvailable >= 43.6 GB` at all times (far exceeding the 12GB minimum safety threshold).
- **Swap Usage**: `Swap <= 1.2 MB` (Zero swap thrashing).
- **Watchdog Script**: Verified and active (`mem_watchdog.sh` monitored `/proc/meminfo` continuously).

---

### System & Hardware Profile

| Hardware Component | Details |
| :--- | :--- |
| **GPU** | AMD Radeon AI PRO R9700 (`gfx1201`, RDNA4, 32 GB VRAM) |
| **CPU** | AMD Ryzen 7 9700X 8-Core Processor (16 Threads) |
| **System Memory** | 64 GB DDR5 System RAM (`MemAvailable: ~43.6 GB` during test) |
| **Storage / SSD** | NVMe SSD `/dev/nvme0n1p5` (Read throughput: SSD streaming supported) |
| **ROCm Toolchain** | ROCm 7.1.52802 / HIP 6.3.3 + clang 22.1.8 |
| **Conda Environment** | `/media/liao/MyHDD/miniforge3/envs/sglang_rocm_qwen36` |

---

### Safe Mode Performance Evaluation Matrix

| Stage | Expert Cache Budget | Context Size (`ctx`) | Generation Tokens | Prefill Speed | Decode Speed | Peak MemAvailable | Peak Swap | Result Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Smoke Test** | `8 GB` | `2048` | 16 | 3.10 t/s | **8.18 t/s** | 43.6 GB | 1.0 MB | **PASSED (Clean OK)** |
| **Stage S0** | `8 GB` | `2048` | 128 | 1.49 t/s | **4.92 t/s** | 43.6 GB | 1.0 MB | **PASSED (Stable)** |
| **Stage S1** | `12 GB` | `2048` | 128 | 1.48 t/s | **5.79 t/s** | 43.6 GB | 1.1 MB | **PASSED (Optimal)** |
| **Stage S1-Ctx4k** | `12 GB` | `4096` | 128 | 1.42 t/s | **5.89 t/s** | 43.6 GB | 1.2 MB | **PASSED (Optimal)** |

*Note: In accordance with `DEEPSEEK_V4_R9700_64GB_SAFE_MODE.md` strict safety rules, aggressive expert cache sizes (24GB / 28GB / 32GB) were explicitly skipped to protect desktop responsiveness and prevent OOM/GPU reset risks.*

---

### Build & Toolchain Engineering Log

1. **GGUF Download**:
   - Model: `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf` (80.76 GB) saved at `/home/liao/deepseek-r9700/models/`.
2. **Repository & PR Integration**:
   - `ds4` PR `#599` (`rocm: fix build on gfx1201 (RDNA4, R9700) — gate the WMMA v1 kernel`) cherry-picked cleanly onto branch `r9700-gfx1201-safe`.
3. **ROCm Header & Library Compatibility Suite**:
   - Solved header dependencies for `rocWMMA`, `rocPRIM`, `hipCUB`, `hipBLASLt`, `hipBLAS-common`.
   - Linked against PyTorch ROCm 7.1 `libhipblaslt.so`, `librocblas.so`, `librocsolver.so`, `libamdhip64.so`, and `libhsa-runtime64.so`.
   - Mapped `amdgcn-link` and `clang-offload-bundler` in PATH.
   - Configured `TensileLibrary` path for `gfx1201`.

---

### Optimal Production Recommendation

For daily local usage on the **AMD Radeon AI PRO R9700 (64GB RAM)**:

- **Recommended Command**:
  ```bash
  LD_LIBRARY_PATH=/media/liao/MyHDD/miniforge3/envs/sglang_rocm_qwen36/lib/python3.11/site-packages/torch/lib:/media/liao/MyHDD/miniforge3/envs/sglang_rocm_qwen36/lib:/home/liao/deepseek-r9700/rocm_deps/usr/lib/x86_64-linux-gnu \
  ./ds4 --rocm \
    -m /home/liao/deepseek-r9700/models/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf \
    --ssd-streaming \
    --ssd-streaming-cache-experts 12GB \
    --ctx 4096 \
    --nothink
  ```
- **Performance Expectation**: ~5.8 tok/s stable inference, ~43.6 GB free system memory, zero swap thrashing, completely safe desktop environment.
