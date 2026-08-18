# Architecture

## 1. System topology

```text
                         SOURCE DOCUMENTS
                      XLSX / DOCX examples
                               |
                    deterministic parsing
                               v
                         +-------------+
                         | Document IR |
                         +------+------+
                                |
                multi-sample alignment / inference
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
        deterministic evidence           semantic reasoning
                                               |
                                               v
                                      +------------------+
                                      | Local LLM Gateway|
                                      +--------+---------+
                                               |
                                    +----------+----------+
                                    |                     |
                                 Qwen 27B             ORINTH 9B
                                    |                     |
                                    +----------+----------+
                                               |
                                      schema validation
                                               |
                                               v
                                      Template Profile
                                               |
                         NEW INPUT             |
                 JSON/CSV/XLSX/DOCX/TEXT       |
                         |                     |
                         v                     |
                  Canonical Data --------------+
                         |
                         v
                   Binding Planner
                         |
            +------------+-------------+
            |                          |
      deterministic rules       unresolved semantic work
            |                          |
            +------------+-------------+
                         |
                         v
                    Document IR
                         |
                +--------+--------+
                |                 |
            XLSX renderer     DOCX renderer
                |                 |
                +--------+--------+
                         |
                         v
                    VALIDATION
       schema / content / structure / style /
        semantics / terminology / round-trip
                         |
                  PASS / REVIEW / FAIL
```

## 2. Two classes of computation

### Deterministic
Use whenever the file format exposes the answer exactly.

Examples:
- sheet names
- merged regions
- row heights / column widths
- fonts / borders / fills
- Word paragraph/run hierarchy
- page margins
- formulas
- list numbering
- required field gates
- known language pattern rendering

### LLM reasoning
Use only where the answer is semantic, contextual or generative.

Examples:
- `勤區` 是否應映射成 `duty_location`
- changing cell values across samples represent which business field
- sentence pattern `{person}於{date}擔服{duty}勤務`
- ambiguous free text → canonical entities
- unresolved prose slot generation

### Hybrid
LLM produces a bounded candidate; deterministic code verifies syntax, schema, references, allowed target fields and invariants.

## 3. Learning-time heavy, runtime light

Template learning may use more LLM calls. Runtime should reuse learned rules whenever possible.

```text
LEARNING
samples -> LLM inference -> evidence-backed rules -> Template Profile

RUNTIME
new data -> known rules -> deterministic generation
                     \
                      -> ambiguity only -> LLM -> validator
```

This protects weaker local models and improves reproducibility.

## 4. Core domain objects

### Document IR
A source-format-neutral tree/graph describing actual document structure and formatting.

Must support:
- document metadata
- sections/pages/sheets
- paragraph/run hierarchy
- tables/rows/cells
- merged regions
- styles and style fingerprints
- formulas
- geometry
- text/value types
- source coordinates
- provenance

### Template Profile
A reusable, versioned generator specification.

Contains:
- structure schema
- style schema
- field schema
- language schema
- mapping rules
- repeated-region rules
- calculation rules
- validation rules
- rendering rules
- inference evidence
- confidence / human corrections

### Canonical Data
Normalized business data separated from its source file layout.

Every value should be able to carry:
- normalized value
- original value
- datatype
- source reference
- confidence
- decision state

## 5. Suggested Python package layout

```text
template_document_engine/
├── pyproject.toml
├── src/docengine/
│   ├── cli/
│   ├── core/
│   │   ├── document_ir/
│   │   ├── template_profile/
│   │   ├── canonical_data/
│   │   ├── evidence/
│   │   └── errors/
│   ├── parsers/
│   │   ├── xlsx/
│   │   └── docx/
│   ├── inference/
│   │   ├── alignment/
│   │   ├── fields/
│   │   ├── language/
│   │   └── calculations/
│   ├── llm/
│   │   ├── gateway/
│   │   ├── adapters/
│   │   ├── prompts/
│   │   ├── routing/
│   │   └── benchmark/
│   ├── ingestion/
│   ├── mapping/
│   ├── generation/
│   ├── renderers/
│   │   ├── xlsx/
│   │   └── docx/
│   ├── validation/
│   └── api/
├── schemas/
├── fixtures/
│   ├── xlsx/
│   ├── docx/
│   └── semantic/
├── benchmarks/
├── tests/
├── artifacts/
└── tools/
```

Recommended libraries:
- `openpyxl` for XLSX mechanics.
- `python-docx` plus direct OOXML access where python-docx does not expose enough detail.
- `pydantic` / JSON Schema for contracts.
- `httpx` for local LLM HTTP calls.
- `pytest` for tests.

Do not use LibreOffice as the core parser. It may be used later only as an optional render-to-preview tool.

## 6. Decision state machine

Semantic decisions should never be only `true/false`.

```text
CANDIDATE
   |
   +-- validated/high confidence --> ACCEPTED
   |
   +-- weak/ambiguous -----------> REVIEW
   |
   +-- contradicted -------------> REJECTED
   |
   +-- insufficient evidence ----> UNKNOWN
```

A generation gate may require some fields to be `ACCEPTED`; other noncritical fields may allow `REVIEW` depending on template policy.

## 7. Learning multiple samples

Do not treat one example as proof of a rule.

For each candidate element:
1. align regions across samples,
2. compare structure/style,
3. identify invariant text/geometry,
4. identify varying values,
5. infer likely field boundary,
6. infer semantics,
7. attach source evidence,
8. assign confidence,
9. preserve ambiguity.

The system should be able to say:
`I can reproduce the layout, but I cannot yet prove whether B7 is a date field or case number.`

That is a valid state.

## 8. Validation philosophy

A successful file open is not success.

Validation dimensions stay separate:
- schema validity
- content completeness
- structure equivalence
- style equivalence
- formula/geometry equivalence
- semantic consistency with source data
- language/terminology adherence
- round-trip equivalence

Never collapse these into one opaque AI similarity score.