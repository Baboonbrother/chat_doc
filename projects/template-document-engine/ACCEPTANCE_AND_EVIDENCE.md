# Acceptance and Evidence Policy

## 1. Node completion

A task node may be marked `DONE` only when all acceptance criteria are satisfied and an evidence record exists.

Minimum evidence:

```yaml
node_id: XLSX-005
status: DONE
implementation_files:
  - src/docengine/parsers/xlsx/styles.py
tests:
  - tests/xlsx/test_styles.py
test_result:
  passed: 17
  failed: 0
commit_sha_or_worktree_diff: "..."
evidence_notes:
  - "font/fill/border/alignment/number-format golden fixture passes"
```

No prose statement such as "implemented successfully" is sufficient.

## 2. Golden fixtures

Fixtures must deliberately cover hard cases.

XLSX:
- multiple sheets
- hidden sheets
- merged cells in both directions
- formulas and cross-sheet references
- number/date formats
- row height / column width
- hidden rows/columns
- freeze panes
- border variants
- repeated rows with different sample counts

DOCX:
- multiple sections
- margins/orientation changes
- paragraph styles
- direct run formatting
- tables with merged cells
- nested tables
- numbering/list levels
- headers/footers
- fields
- repeated semantic sections

Semantic:
- obvious labels
- ambiguous labels
- misleading labels
- value-only inference
- missing data
- contradictory data
- extra unknown fields
- Chinese official/professional terminology patterns

## 3. Round-trip

For supported information:

```text
source file
 -> parse
 -> Document IR A
 -> render
 -> generated file
 -> parse
 -> Document IR B
 -> normalized diff
```

The comparison must explicitly declare tolerances and unsupported OOXML features.

## 4. LLM acceptance

For LLM nodes:
- output schema validity is necessary but not sufficient,
- benchmark cases must include wrong-but-valid JSON,
- target field IDs must be checked against known schema,
- source references must exist,
- unsupported invented facts are blocking.

## 5. Integration gate

v0.1 is not ready until:
- XLSX learn→generate golden scenario passes,
- DOCX learn→generate golden scenario passes,
- Qwen 27B and ORINTH 9B have been run on the same benchmark suite,
- router recommendation exists,
- offline/no-LLM rendering works for a fully learned template,
- audit manifest/replay works,
- known limitations are explicit.