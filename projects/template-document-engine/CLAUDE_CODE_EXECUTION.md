# Claude Code Execution Protocol

You are implementing the Template-Guided Document Generation Engine described in this directory.

## Mandatory reading order

Read completely before coding:
1. `README.md`
2. `ARCHITECTURE.md`
3. `LLM_GATEWAY.md`
4. `SCHEMAS_AND_CONTRACTS.md`
5. `ACCEPTANCE_AND_EVIDENCE.md`
6. `TASK_REGISTRY.yaml`

## Operating rule

Treat `TASK_REGISTRY.yaml` as an execution DAG, not a checklist to cosmetically update.

At each cycle:

1. Parse the registry.
2. Find nodes whose dependencies are DONE and whose own status is TODO/READY.
3. Select the smallest coherent implementation slice.
4. Implement only what its objective requires while preserving architecture contracts.
5. Add/modify fixtures and tests.
6. Run relevant tests.
7. Record evidence.
8. Change the node to DONE only when acceptance is met.
9. Commit the coherent slice.
10. Continue to the next READY node.

If a design flaw is discovered, do not silently bypass it. Record a design decision and repair the contract/registry.

## Priority

Build the dependency roots first:
- FND contracts
- XLSX/DOCX deterministic parsers
- LLM gateway contract and adapters
- template learning
- canonical ingestion
- generation
- validation
- end-to-end scenarios

Do not implement UI before INT-008.

## Local LLM rule

The actual local endpoints/model IDs may differ. Discover or accept configuration from environment/config file.

Expected conceptual aliases:
- `qwen27b`
- `orinth9b`

Do not write a direct Ollama/vLLM-specific call into semantic business logic. All model calls go through the gateway.

If neither local model is reachable in the current environment:
- implement gateway/adapters and mocked contract tests,
- mark live-model benchmark nodes BLOCKED, not DONE,
- provide the exact command/config needed to run the live benchmark locally.

## No fake completion

Do not:
- mark benchmark nodes done using mocked models,
- claim style fidelity from a file merely opening,
- replace semantic inference with hardcoded label dictionaries and then claim LLM support,
- skip provenance,
- swallow UNKNOWN states,
- create 92 separate markdown task files.

The registry is the source of task state.

## First milestone

The first meaningful milestone is not generation. It is:

```text
sample.xlsx -> Document IR -> sample_roundtrip.xlsx -> Document IR'
```

with a readable diff and golden tests.

Then do the same for DOCX.

## Second milestone

Connect one semantic task through both local model adapters, for example `FIELD_SEMANTIC_INFERENCE`, and produce a real A/B benchmark artifact.

## Third milestone

Use 3+ same-type samples to learn one Template Profile, then feed new Canonical Data and regenerate a valid document.

## Required reporting after each implementation session

Return:
- branch / commit
- nodes completed
- nodes blocked
- tests run and exact results
- artifacts generated
- next READY nodes
- any architectural decisions made

Never report only "done".