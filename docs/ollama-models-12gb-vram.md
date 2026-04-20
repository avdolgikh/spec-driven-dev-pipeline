# Ollama Models for 12 GB VRAM (RTX 4070 class)

## Purpose

Reference for picking local Ollama models to drive the pipeline's roles
(test-writer, implementer, reviewer) on a ~12 GB consumer GPU. Grounded in
the Ollama public library and independent benchmarks as of April 2026.

Pipeline context: models are invoked via `OpenCodeProvider`
(`providers/opencode.py`), which shells out to `opencode.cmd` and expects
structured `FILE: <path>` blocks in stdout. The benchmark report in
`README.md` (2026-04-10) showed the dominant failure mode on this hardware
is **format compliance**, not raw capability — pick models accordingly.

## Hardware envelope

- GPU: RTX 4070 / 4070 Ti — 12 GB GDDR6X
- Quantization sweet spot: **Q4_K_M** (best quality/size trade-off)
- VRAM budget for model weights: ~10 GB (leave ~2 GB for KV cache + OS)
- Approximate VRAM at Q4_K_M: `params × 0.55 GB / B params` (dense)
- MoE total params still load to VRAM; active params drive throughput

## Quantization cheat-sheet

| Quant   | Bits/param | Quality       | When to use                    |
|---------|------------|---------------|--------------------------------|
| Q8_0    | ~8.5       | near-lossless | small models (≤ 7B) on 12 GB   |
| Q6_K    | ~6.6       | excellent     | 7–9 B sweet spot               |
| Q5_K_M  | ~5.7       | very good     | 9–13 B fits comfortably        |
| Q4_K_M  | ~4.8       | good          | 13–24 B dense; 30 B MoE (tight)|
| Q3_K_M  | ~3.9       | noticeable loss | only if nothing else fits    |
| Q2_K    | ~2.7       | unreliable    | avoid for code tasks           |

---

## Recommended by pipeline role

### Test-writer / implementer (economy tier — code generation)

These need strong code ability and, critically, **format discipline** to
emit `FILE:` blocks without prose drift.

| Model                         | Params        | Ollama tag                        | Approx VRAM (Q4_K_M) | Notes                                                                                  |
|-------------------------------|---------------|-----------------------------------|----------------------|----------------------------------------------------------------------------------------|
| **Qwen 3-Coder** (dense)      | 7 B           | `qwen3-coder:7b`                  | ~4.5 GB              | Comfortable fit. Fastest code model at this size. Good starting point.                 |
| **Qwen 3-Coder** (MoE)        | 30 B / 3 B act| `qwen3-coder:30b-a3b-q4_K_M`      | ~16–17 GB            | **Tight** — needs partial CPU offload on 12 GB; ~2–3× faster than 32 B dense if offload tolerable. Current repo default. |
| **DeepSeek-Coder-V2**         | 16 B / 2.4 B act | `deepseek-coder-v2:16b`         | ~9 GB                | MoE, fits comfortably. Strong on multi-file edits.                                     |
| **DeepSeek-Coder**            | 6.7 B         | `deepseek-coder:6.7b`             | ~4 GB                | Dense. Small, fast, solid code output.                                                 |
| **Codestral**                 | 22 B          | `codestral:22b`                   | ~12–13 GB            | **Just over budget** at Q4. Use Q3_K_M to fit (~10 GB).                                 |
| **StarCoder 2**               | 15 B          | `starcoder2:15b`                  | ~9 GB                | Fill-in-the-middle strong; instruction-following weaker.                               |
| **StarCoder 2**               | 7 B           | `starcoder2:7b`                   | ~4.5 GB              | Fast, capable at short completions.                                                    |
| **Devstral Small**            | 24 B          | `devstral:24b`                    | ~13–14 GB            | **Over budget** without offload. Tuned for agentic coding workflows; worth trying with `--num-gpu-layers` tuning. |

### Reviewer (premium tier — careful judgment, long context)

Review gets the full spec + test packet + artifact snapshot — prioritize
**instruction-following** and **structured output** (JSON decision).

| Model                 | Params        | Ollama tag           | Approx VRAM (Q4_K_M) | Notes                                                                  |
|-----------------------|---------------|----------------------|----------------------|------------------------------------------------------------------------|
| **Qwen 3.5**          | 9.7 B         | `qwen3.5:latest`     | ~6 GB                | Comfortable. Thinking mode available. Currently downloaded.            |
| **Gemma 3**           | 9 B           | `gemma3:9b`          | ~6 GB                | Strong instruction-following.                                          |
| **Gemma 3**           | 27 B          | `gemma3:27b`         | ~15 GB               | **Over budget** at Q4_K_M; needs Q3 (~12 GB) or offload.               |
| **Phi-4**             | 14 B          | `phi4:14b`           | ~8 GB                | Reasoning-focused, good at structured output.                           |
| **Phi-4-Reasoning**   | 14 B          | `phi4-reasoning:14b` | ~8 GB                | Explicit chain-of-thought; better for reviewer role than implementer.  |
| **DeepSeek-R1**       | 14 B          | `deepseek-r1:14b`    | ~8 GB                | Reasoning specialist. Slow (thinks before answering) but thorough.     |
| **Mistral-Nemo**      | 12 B          | `mistral-nemo:12b`   | ~7 GB                | 128 K context — useful if spec + artifact snapshot is large.           |
| **GLM-4.7-Flash**     | 30 B / 3 B act| `glm-4.7-flash`      | ~16–17 GB            | **Tight** — needs offload. Currently downloaded. Strong at structured output in benchmark. |

### Too large for this box (reference only)

| Model                   | Params         | Why it's listed                                          |
|-------------------------|----------------|----------------------------------------------------------|
| Llama 4 Scout           | 109 B MoE      | Out of reach without multi-GPU.                          |
| Llama 4 Maverick        | 400 B MoE      | Server-class only.                                       |
| DeepSeek-V3             | 671 B / 37 B act| Server-class only.                                      |
| Qwen 3 235B flagship    | 235 B MoE      | Out of reach.                                            |
| Gemma 4 (flagship)      | 26 B (MoE)     | ~14 GB at Q4 — feasible with offload only.               |

---

## Compact models (fit with headroom; use for fast drafts or embeddings)

| Model              | Params     | Ollama tag              | Purpose                                        |
|--------------------|------------|-------------------------|------------------------------------------------|
| Llama 3.2          | 3 B        | `llama3.2:3b`           | General chat, low-latency.                     |
| Phi-4-mini         | 3.8 B      | `phi4-mini:3.8b`        | Lightweight reasoning.                         |
| Gemma 3            | 4 B        | `gemma3:4b`             | Efficient general chat.                        |
| Qwen 3             | 4 B        | `qwen3:4b`              | Tool-use capable at small size.                |
| SmolLM2            | 1.7 B      | `smollm2:1.7b`          | Edge / smoke tests only.                       |
| **Embeddings**     |            |                         |                                                |
| nomic-embed-text   | 137 M      | `nomic-embed-text`      | Long-context embeddings (future RAG).          |
| mxbai-embed-large  | 335 M      | `mxbai-embed-large`     | State-of-the-art sentence embeddings.          |
| bge-m3             | 567 M      | `bge-m3`                | Multilingual embeddings.                       |

---

## Format-compliance caveat (read before picking)

The benchmark report (`benchmarks/benchmark-calc-report.md`, 2026-04-10)
tested four local models. **Only GLM-4.7-Flash produced parseable `FILE:`
blocks**; the other three (Qwen 3.5, Gemma 4, Qwen3-Coder) failed at
Stage 1 with prose or tool-call JSON instead.

Implication: the right model for this pipeline is not simply "biggest
that fits." It is "biggest that fits **and** follows the FILE block
protocol reliably across revisions." Today that short list is:

1. GLM-4.7-Flash (tight fit, best observed compliance)
2. Qwen3-Coder 30B-A3B (tight fit, compliance improves with grammar)
3. Qwen3-Coder 7 B (comfortable fit, untested here — worth trying)
4. DeepSeek-Coder-V2 16 B (comfortable fit, not yet benchmarked)

The planned GBNF grammar enforcement (see
`specs/pipeline-improvement-plan-spec.md` REQ-2) would widen this list by
mechanically enforcing compliance — but note the open critique in
`specs/pipeline-improvement-plan-critique.md` about its limits.

---

## Pulling & running

```bash
# Pull
ollama pull qwen3-coder:7b
ollama pull deepseek-coder-v2:16b
ollama pull phi4:14b
ollama pull mistral-nemo:12b

# Quick smoke test (ensure model responds)
ollama run qwen3-coder:7b "Write a Python function that returns 42."

# Use with the pipeline's OpenCode provider
OPENCODE_MODEL=ollama/qwen3-coder:7b \
  uv run python scripts/run_pipeline.py <task-id> --provider opencode --repo-root <path>
```

For models that exceed 12 GB (e.g. Qwen3-Coder 30B-A3B, GLM-4.7-Flash),
tune CPU offload:

```bash
# Offload N layers to CPU; throughput drops but model loads
ollama run qwen3-coder:30b-a3b-q4_K_M --num-gpu-layers 30
```

Partial offload costs 3–10× throughput on average — acceptable for slow
overnight runs, painful for interactive iteration.

---

## Sources

- [Ollama public library](https://ollama.com/library)
- [Ollama VRAM requirements guide (2026)](https://localllm.in/blog/ollama-vram-requirements-for-local-llms)
- [Best Local LLMs for RTX 40 Series](https://apxml.com/posts/best-local-llm-rtx-40-gpu)
- [Best Ollama Models for Coding (2026)](https://www.aimadetools.com/blog/best-ollama-models-coding-2026/)
- [Best Local AI Coding Models for Ollama (2026)](https://localaimaster.com/models/best-local-ai-coding-models)
- [Qwen3-Coder 30B hardware requirements](https://www.arsturn.com/blog/running-qwen3-coder-30b-at-full-context-memory-requirements-performance-tips)
- [Qwen3-Coder on Ollama](https://ollama.com/library/qwen3-coder)
- [Open-Source LLM Comparison (2026)](https://till-freitag.com/en/blog/open-source-llm-comparison)
- Internal: `benchmarks/benchmark-calc-report.md` (2026-04-10)
