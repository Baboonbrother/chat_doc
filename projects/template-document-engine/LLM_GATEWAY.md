# Local LLM Gateway and Benchmark

## 1. Requirement

The engine must support local LLMs through one provider-neutral gateway. Initial target models:

- Qwen 27B
- ORINTH 9B

Model IDs and endpoint URLs are runtime configuration, not source-code constants.

Preferred transport is OpenAI-compatible HTTP. Example configuration:

```yaml
models:
  qwen27b:
    provider: openai_compatible
    base_url: http://127.0.0.1:8000/v1
    model: YOUR_QWEN_MODEL_ID
    timeout_seconds: 120

  orinth9b:
    provider: openai_compatible
    base_url: http://127.0.0.1:8001/v1
    model: YOUR_ORINTH_MODEL_ID
    timeout_seconds: 90
```

If the actual local runtimes expose another protocol, add adapters behind the same contract.

## 2. Gateway request

Logical request:

```json
{
  "task_id": "FIELD_SEMANTIC_INFERENCE",
  "prompt_version": "1.0.0",
  "model_policy": "auto",
  "context": {
    "field_id": "sheet1:B7",
    "label": "勤區",
    "samples": ["石牌", "明德", "天母"]
  },
  "output_schema": {
    "type": "object",
    "required": ["semantic_name", "datatype", "confidence"],
    "properties": {
      "semantic_name": {"type": "string"},
      "datatype": {"type": "string"},
      "confidence": {"type": "number"}
    }
  }
}
```

Logical response:

```json
{
  "task_id": "FIELD_SEMANTIC_INFERENCE",
  "model_id": "qwen27b",
  "prompt_version": "1.0.0",
  "valid": true,
  "output": {
    "semantic_name": "duty_location",
    "datatype": "string",
    "confidence": 0.91
  },
  "latency_ms": 8210,
  "attempts": 1
}
```

## 3. Hard requirements

Every model call must:
- request structured output,
- validate against an output schema,
- have bounded timeout,
- have bounded retries,
- log model ID and prompt version,
- preserve evidence IDs used in context,
- distinguish transport failure, malformed JSON and semantic rejection.

Never silently accept malformed JSON after regex scraping if it changes semantic content.

## 4. Prompt registry

Prompts belong in a task registry, not scattered through Python functions.

Initial task IDs:
- `FIELD_SEMANTIC_INFERENCE`
- `FIELD_RELATION_INFERENCE`
- `LANGUAGE_PATTERN_EXTRACTION`
- `ENTITY_EXTRACTION`
- `CANONICAL_FIELD_MAPPING`
- `TEMPLATE_SLOT_MAPPING`
- `CONTROLLED_FREE_TEXT_GENERATION`
- `SEMANTIC_CONSISTENCY_REVIEW`

Each prompt has:
- version
- system instructions
- input schema
- output schema
- examples
- evaluation metric

## 5. Model routing

Do not encode:
`if hard: qwen27b else: orinth9b`
until benchmarks support that policy.

Initial benchmark measures:
- exact/semantic accuracy
- JSON-valid rate
- schema-valid rate
- unsupported-field hallucination rate
- source-provenance correctness
- latency
- timeout/retry rate

Potential router after measurement:

```text
known deterministic mapping -> no LLM
easy semantic task          -> best benchmarked low-cost model
ambiguous task              -> stronger model
high-risk ambiguity         -> both models
disagreement                -> REVIEW / human
```

Two models disagreeing is not a vote. It is evidence of uncertainty.

## 6. Confidence

Model self-reported confidence is not trusted as calibrated probability.

Final decision confidence may combine:
- cross-sample consistency,
- deterministic datatype compatibility,
- label/value evidence,
- benchmark calibration for the task/model,
- model agreement/disagreement,
- human correction history.

Store component scores separately.

## 7. Benchmark artifacts

One command should produce machine-readable and human-readable output:

```bash
docengine benchmark --models qwen27b,orinth9b --suite semantic_v1
```

Artifacts:
- `benchmark.json`
- `benchmark.md`
- per-case predictions
- invalid-output cases
- latency distribution summary
- router recommendation

The router must cite the benchmark version that justified its policy.