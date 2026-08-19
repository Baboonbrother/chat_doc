# Schemas and Contracts

This file defines the minimum semantic shape. Claude Code may implement these as Pydantic models plus exported JSON Schema.

## Document IR

```yaml
schema_version: "1.0"
document_id: "..."
source:
  kind: xlsx | docx | generated
  sha256: "..."
format:
  type: xlsx | docx
nodes:
  - id: "..."
    kind: sheet | section | paragraph | run | table | row | cell
    parent_id: "..."
    order: 0
    value: null
    value_type: string | number | date | boolean | formula | null
    style_ref: "style:abc"
    geometry: {}
    source_ref: {}
styles:
  style:abc:
    font: {}
    fill: {}
    border: {}
    alignment: {}
    number_format: null
relationships: []
```

Requirements:
- stable IDs within one parse,
- deterministic serialization,
- source coordinates,
- explicit merged regions and formulas,
- no reliance on Python object identity.

## Template Profile

```yaml
schema_version: "1.0"
template_id: "..."
template_version: "..."
learned_from:
  sample_ids: []
  source_hashes: []
structure_rules: []
style_rules: []
fields:
  - field_id: "..."
    semantic_name: "duty_location"
    datatype: string
    cardinality: one | optional | many
    required: true
    locations: []
    confidence: 0.91
    evidence_ids: []
language_rules: []
mapping_rules: []
calculation_rules: []
validation_rules: []
rendering_rules: []
human_patches: []
```

## Canonical Data

```yaml
schema_version: "1.0"
data_id: "..."
values:
  report_date:
    normalized: "2026-08-20"
    original: "115/8/20"
    datatype: date
    source_refs: []
    confidence: 1.0
    state: ACCEPTED
  staff:
    normalized:
      - employee_name: "王小明"
        duty_location: "石牌"
    datatype: list
    source_refs: []
    confidence: 0.95
    state: ACCEPTED
```

## Evidence Record

```yaml
evidence_id: "ev-..."
kind: deterministic | sample | model | human
source_refs: []
task_id: null
model_id: null
prompt_version: null
claim: "..."
confidence_components: {}
created_at: "..."
```

## Semantic Decision Record

```yaml
decision_id: "dec-..."
subject_id: "..."
decision_type: field_semantic | field_mapping | language_pattern | relation
proposal: {}
state: CANDIDATE | ACCEPTED | REVIEW | REJECTED | UNKNOWN
evidence_ids: []
validator_results: []
```

## Invariants

- Every inferred semantic field must have evidence.
- Every generated dynamic value must trace to Canonical Data or an approved derived rule.
- Every LLM-generated prose span must record the data/evidence supplied to the model.
- UNKNOWN and REVIEW are first-class states.
- Human correction creates a new auditable patch/version; it does not mutate historical evidence.