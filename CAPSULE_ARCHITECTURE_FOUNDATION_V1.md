# Capsule Architecture Foundation v1

> Goal: establish a long-lived, extensible foundation for Capsule App Hub before local LLM implementation begins.
>
> Core design principle: **inherit contracts, compose behavior, generate documentation, and propagate invalidation through a dependency graph.**

## 0. Why this document exists

As the number of capsules grows, the system must not require an LLM to reread every document whenever a low-level definition changes. The architecture therefore treats every capsule as a versioned graph node with explicit contracts and dependencies.

The system must optimize for:

1. **Local reasoning** — an LLM can modify one capsule without loading the whole repository.
2. **Explicit impact** — a change knows exactly which descendants/dependents may be invalidated.
3. **No semantic smuggling** — atomic capsules cannot secretly embed higher-level conclusions.
4. **Stable identities** — a concept remains the same concept even when its implementation changes.
5. **Replaceability** — implementations, algorithms, brokers, and models can be swapped independently.
6. **Machine navigability** — the structure can later become a DAG, graph database, knowledge graph, embedding map, or agent routing layer.
7. **Generated views** — README/index/graph pages are outputs, not primary truth.

---

# 1. Capsule taxonomy: orthogonal axes, not exploding subclasses

Do not create a different top-level class for every combination. Every capsule is described by orthogonal metadata.

## 1.1 Domain

```text
EXECUTION   executable capability / operation
SEMANTIC    concept / metric / state / event / relation
RESEARCH    hypothesis / experiment / evidence / finding (reserved, may be enabled later)
```

## 1.2 Composition

```text
ATOMIC      smallest unit that preserves the intended meaning/capability
COMPOSITE   derives/orchestrates other capsules through declared references
```

## 1.3 Role

Role is metadata, not another inheritance tree.

Examples:

```text
EXECUTION roles:
CONNECTOR
QUERY
TRANSFORM
VALIDATOR
WORKFLOW
ACTUATOR
MONITOR

SEMANTIC roles:
OBSERVATION
METRIC
CONCEPT
STATE
EVENT
RELATION

RESEARCH roles:
HYPOTHESIS
EXPERIMENT
EVIDENCE
FINDING
REFUTATION
```

Examples:

```text
BrokerConnection:
  domain: EXECUTION
  composition: ATOMIC
  role: CONNECTOR

PrepareOrder:
  domain: EXECUTION
  composition: COMPOSITE
  role: WORKFLOW

VolumeActivity:
  domain: SEMANTIC
  composition: ATOMIC
  role: METRIC

RetailPanic:
  domain: SEMANTIC
  composition: COMPOSITE
  role: STATE
```

---

# 2. Inheritance model: shallow contract inheritance only

## 2.1 What may be inherited

A capsule may inherit **contract metadata and schema requirements**, such as:

- identity fields
- version fields
- input/output envelope
- provenance envelope
- confidence envelope
- run status envelope
- logging envelope
- health state envelope
- lifecycle fields

## 2.2 What must NOT be inherited

Do not inherit executable business logic through a deep class hierarchy.

Forbidden pattern:

```text
CapsuleBase
  -> SemanticCapsule
    -> MarketSemanticCapsule
      -> SentimentCapsule
        -> FearCapsule
          -> RetailFearCapsule
```

This creates a fragile-base-class problem: a change at the top can silently affect many descendants.

## 2.3 Maximum inheritance depth

Recommended hard rule:

```text
MAX_CONTRACT_INHERITANCE_DEPTH = 2
```

Example:

```text
CapsuleContract
  -> SemanticContract
```

A concrete capsule then **references** `SemanticContract`; it does not continue subclassing indefinitely.

## 2.4 Behavior uses composition

Use explicit dependencies:

```text
RetailPanic
  DERIVES_FROM RetailFlow
  DERIVES_FROM PriceResponse
  DERIVES_FROM VolumeActivity
  DERIVES_FROM Persistence
```

not:

```text
class RetailPanic(VolumeActivity, RetailFlow, PriceResponse, Persistence)
```

Multiple inheritance of capsule behavior is forbidden.

---

# 3. Source of truth hierarchy

The repository should distinguish authoritative machine contracts from generated human documentation.

```text
contracts/              authoritative schemas
registry/               authoritative capsule manifests
relations/              authoritative typed edges
implementations/        executable implementations
instances/              runtime outputs / observations (normally external DB, not Git)
research/               evidence and evaluation artifacts
views/                  GENERATED; never manually authoritative
```

Human Markdown is useful, but it must not become the only place where critical relationships live.

## 3.1 Canonical rule

```text
Machine-readable contract > generated documentation > prose commentary
```

If Markdown conflicts with schema/manifest, schema/manifest wins.

---

# 4. Base capsule manifest

Every capsule has one small manifest. It should remain readable by a weak LLM.

Example:

```yaml
capsule_id: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
schema_version: 1
capsule_version: 1.2.0

domain: SEMANTIC
composition: ATOMIC
role: METRIC

contract:
  extends: contracts/semantic.schema.json

identity:
  concept_id: volume_activity
  stable: true

inputs:
  - market.volume
  - market.turnover
  - market.trading_value

outputs:
  - activity_score
  - activity_percentile

forbidden_semantics:
  - PANIC
  - CONFIDENCE
  - ACCUMULATION
  - DISTRIBUTION
  - EUPHORIA

dependencies: []

implementations:
  active: volume_activity_v2
  available:
    - volume_activity_v1
    - volume_activity_v2

provenance:
  required: true
```

Composite example:

```yaml
capsule_id: SEMANTIC.COMPOSITE.RETAIL_PANIC
schema_version: 1
capsule_version: 1.0.0

domain: SEMANTIC
composition: COMPOSITE
role: STATE

contract:
  extends: contracts/semantic.schema.json

inputs_from_capsules:
  - capsule: SEMANTIC.ATOMIC.RETAIL_FLOW
    edge: DERIVES_FROM
    version_range: ">=1,<2"
  - capsule: SEMANTIC.ATOMIC.PRICE_RESPONSE
    edge: DERIVES_FROM
    version_range: ">=1,<2"
  - capsule: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
    edge: CONTRIBUTES_TO
    version_range: ">=1,<2"
  - capsule: SEMANTIC.COMPOSITE.PERSISTENCE
    edge: CONTRIBUTES_TO
    version_range: ">=1,<2"

outputs:
  - score
  - confidence

provenance:
  required: true
```

---

# 5. Stable concept identity vs implementation identity

Never make an algorithm version equal to the concept identity.

```text
Concept:
SEMANTIC.ATOMIC.VOLUME_ACTIVITY

Implementations:
volume_activity_v1
volume_activity_v2
volume_activity_v3
```

Graph relation:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
  IMPLEMENTED_BY -> volume_activity_v1
  IMPLEMENTED_BY -> volume_activity_v2
  IMPLEMENTED_BY -> volume_activity_v3
```

Benefits:

- changing a formula does not rename the concept;
- historical results can record which implementation generated them;
- multiple implementations can be A/B tested;
- rollback is cheap;
- downstream concepts depend on an interface, not a concrete formula unless explicitly pinned.

---

# 6. Typed graph edges

Never store anonymous `A -> B` edges.

Initial edge vocabulary:

```text
USES
PRODUCES
DERIVES_FROM
CONTRIBUTES_TO
REQUIRES
MEASURES
DESCRIBES
IMPLEMENTS
IMPLEMENTED_BY
SUPPORTS
CONTRADICTS
REFINES
VALIDATES
TRIGGERS
TEMPORALLY_PRECEDES
REPLACES
DEPRECATED_BY
```

Each relation should be machine-readable:

```yaml
from: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
type: CONTRIBUTES_TO
to: SEMANTIC.COMPOSITE.RETAIL_PANIC
introduced_in: 1.0.0
```

Edges are first-class assets because impact analysis depends on them.

---

# 7. Change propagation and local invalidation

This is the most important scalability mechanism.

A low-level edit must not trigger a full-repository reread.

## 7.1 Every contract has a content hash

Example:

```text
contract_hash = SHA256(normalized_contract)
implementation_hash = SHA256(relevant_source_tree)
```

Every dependent capsule records the hashes it was last validated against.

```yaml
validated_against:
  SEMANTIC.ATOMIC.VOLUME_ACTIVITY:
    contract_hash: abc123...
    capsule_version: 1.2.0
```

## 7.2 Change classes

Every modification must be classified:

```text
DOC_ONLY
PATCH
NON_BREAKING_CONTRACT
BREAKING_CONTRACT
SEMANTIC_CHANGE
IMPLEMENTATION_ONLY
RELATION_CHANGE
```

## 7.3 Propagation rules

```text
DOC_ONLY
  -> no invalidation

IMPLEMENTATION_ONLY
  -> rerun tests/evaluation for this implementation
  -> downstream invalidation only when behavior contract/evidence threshold says so

NON_BREAKING_CONTRACT
  -> validate direct dependents
  -> do not automatically invalidate transitive graph

BREAKING_CONTRACT
  -> invalidate direct dependents
  -> recursively inspect their outputs and propagate only if their effective contract/result changes

SEMANTIC_CHANGE
  -> invalidate all semantic dependents reachable through meaning-bearing edges

RELATION_CHANGE
  -> invalidate the affected composite and graph views
```

## 7.4 Reverse dependency index

Generate a reverse index:

```text
VolumeActivity
  <- RetailPanic
  <- SpeculativeHeat
  <- PanicWithAbsorption
```

When `VolumeActivity` changes, the system computes the impacted subgraph in milliseconds. The LLM receives only that subgraph.

---

# 8. Effective contract compilation

To reduce LLM context requirements, never force an agent to mentally resolve inheritance.

A compiler should transform:

```text
Base contract
+ domain contract
+ capsule manifest
+ referenced traits
```

into one flattened file:

```text
.build/effective_contracts/<capsule_id>.json
```

An LLM modifying a capsule should normally read only:

```text
1. effective contract
2. capsule manifest
3. current implementation
4. direct dependencies
5. direct dependents
6. relevant tests
```

It should NOT need the entire corpus.

---

# 9. Traits instead of multiple inheritance

Cross-cutting capabilities such as logging, health, provenance, runtime status, or confidence should be explicit traits.

Example:

```yaml
traits:
  - RUN_LOG_V1
  - HEALTH_STATUS_V1
  - PROVENANCE_V1
  - CONFIDENCE_OUTPUT_V1
```

Traits are merged by a deterministic compiler with conflict detection.

Rules:

1. traits cannot override capsule identity;
2. traits cannot silently redefine existing fields;
3. conflicts fail compilation;
4. traits are versioned;
5. trait changes run reverse-impact analysis.

This gives class-like reuse without deep inheritance.

---

# 10. Atomic vs Composite invariant

Core invariant:

> **An Atomic Capsule is the smallest capability or concept that cannot be decomposed further without losing its intended meaning. A Composite Capsule must build through references to other capsules and must not secretly reimplement their lower-level logic.**

Enforce mechanically.

For a `COMPOSITE` capsule:

- dependencies must be declared;
- provenance must identify upstream capsules;
- duplicated implementations of upstream metrics are forbidden;
- direct raw-data access should be denied unless explicitly whitelisted by contract.

This prevents a Composite capsule from quietly becoming a monolith.

---

# 11. Semantic inference boundary

Atomic semantic capsules may output observations/measurements but must not smuggle high-level psychological labels.

Example:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
  MAY: activity_score, percentile, zscore
  MUST NOT: PANIC, CONFIDENCE, EUPHORIA, DISTRIBUTION
```

Higher-order semantic inference belongs to Composite capsules.

Example:

```text
RetailFlow + PriceResponse + VolumeActivity + Persistence
  -> SEMANTIC.COMPOSITE.RETAIL_PANIC
```

This distinction must be machine-validated.

---

# 12. Definition vs runtime instance

Concept definitions and time-specific values are different entities.

Definition:

```text
SEMANTIC.COMPOSITE.RETAIL_PANIC
```

Runtime instances:

```text
RetailPanic @ 2026-08-11 -> 0.32
RetailPanic @ 2026-08-12 -> 0.57
RetailPanic @ 2026-08-13 -> 0.81
```

Do not create a new concept capsule for each date.

Runtime instance should record:

```yaml
capsule_id: SEMANTIC.COMPOSITE.RETAIL_PANIC
capsule_version: 1.0.0
implementation_id: retail_panic_v1
as_of: 2026-08-13
score: 0.81
confidence: 0.72
input_snapshot_hash: ...
upstream_instance_ids: [...]
```

---

# 13. Documentation strategy for thousands of capsules

Do NOT create hand-maintained giant Markdown files containing every capsule.

Instead:

```text
registry/*.yaml           source of truth
relations/*.yaml          source of truth
contracts/*.json          source of truth

views/README_INDEX.md     generated
views/GRAPH.md            generated
views/DOMAIN_EXECUTION.md generated
views/DOMAIN_SEMANTIC.md  generated
views/IMPACT/*.md         generated
```

Generated documents may be deleted and rebuilt at any time.

## 13.1 One capsule, one small local README only when useful

Optional capsule-local prose should explain:

```text
what it means
what it does not mean
examples
known limitations
```

It must not duplicate machine contracts.

---

# 14. LLM modification protocol

Before modifying a capsule, the local LLM should call a tool like:

```bash
capsule impact SEMANTIC.ATOMIC.VOLUME_ACTIVITY
```

Expected output:

```text
TARGET
SEMANTIC.ATOMIC.VOLUME_ACTIVITY

DIRECT_DEPENDENTS
- SEMANTIC.COMPOSITE.RETAIL_PANIC
- SEMANTIC.COMPOSITE.SPECULATIVE_HEAT

TRANSITIVE_DEPENDENTS
- SEMANTIC.COMPOSITE.PANIC_WITH_ABSORPTION

FILES_TO_READ
- registry/semantic/volume_activity.yaml
- .build/effective_contracts/SEMANTIC.ATOMIC.VOLUME_ACTIVITY.json
- implementations/semantic/volume_activity/v2.py
- tests/semantic/test_volume_activity.py
- registry/semantic/retail_panic.yaml
- registry/semantic/speculative_heat.yaml

FILES_NOT_REQUIRED
all other capsules
```

The harness should explicitly tell the LLM:

> Do not search the whole repository unless the impact tool returns `GLOBAL_IMPACT` or compilation fails to resolve dependencies.

---

# 15. Change receipts

Every modification should generate a machine-readable receipt.

```yaml
change_id: CHG-2026-08-13-001
target: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
change_class: NON_BREAKING_CONTRACT
old_contract_hash: ...
new_contract_hash: ...

directly_checked:
  - SEMANTIC.COMPOSITE.RETAIL_PANIC
  - SEMANTIC.COMPOSITE.SPECULATIVE_HEAT

invalidated:
  - SEMANTIC.COMPOSITE.RETAIL_PANIC

not_invalidated:
  - SEMANTIC.COMPOSITE.SPECULATIVE_HEAT

reason: output schema unchanged; behavior tolerance passed except RetailPanic calibration threshold
```

This becomes long-term memory for future LLMs.

---

# 16. Version rules

Use Semantic Versioning for capsule contracts.

```text
MAJOR = breaking contract or meaning change
MINOR = backward-compatible field/capability addition
PATCH = implementation/document/test fix preserving contract and meaning
```

Separate:

```text
capsule_version
implementation_version
schema_version
trait_version
```

Never overload one version number for all four.

---

# 17. Deprecation instead of destructive edits

Old concepts and contracts should usually be deprecated, not silently rewritten.

Example:

```yaml
status: DEPRECATED
deprecated_by: SEMANTIC.COMPOSITE.RETAIL_STRESS
migration_note: ...
```

Graph:

```text
RETAIL_PANIC_V1 --DEPRECATED_BY--> RETAIL_STRESS
```

Historical runtime instances continue to point to the original definition/version.

---

# 18. Storage recommendation

Start simple. Do not require Neo4j on day one.

Phase 1:

```text
Git + YAML/JSON + generated adjacency indexes
```

Phase 2:

```text
SQLite/DuckDB graph projection for local queries
```

Phase 3, only when justified:

```text
property graph / knowledge graph backend
```

The logical graph model must not depend on a specific graph database.

---

# 19. Proposed repository layout

```text
capsule-hub/
├── contracts/
│   ├── capsule.schema.json
│   ├── execution.schema.json
│   ├── semantic.schema.json
│   ├── research.schema.json
│   └── traits/
│       ├── run_log_v1.schema.json
│       ├── health_status_v1.schema.json
│       ├── provenance_v1.schema.json
│       └── confidence_v1.schema.json
│
├── registry/
│   ├── execution/
│   │   ├── atomic/
│   │   └── composite/
│   ├── semantic/
│   │   ├── atomic/
│   │   └── composite/
│   └── research/
│       ├── atomic/
│       └── composite/
│
├── relations/
│   └── edges.yaml
│
├── implementations/
│   ├── execution/
│   └── semantic/
│
├── tests/
│   ├── contracts/
│   ├── registry/
│   ├── graph/
│   └── capsules/
│
├── tools/
│   ├── compile_contracts.py
│   ├── validate_registry.py
│   ├── build_graph.py
│   ├── impact.py
│   ├── generate_views.py
│   └── change_receipt.py
│
├── .build/
│   ├── effective_contracts/
│   ├── graph/
│   └── reverse_dependencies/
│
└── views/
    └── GENERATED_ONLY.md
```

---

# 20. Compiler responsibilities

`compile_contracts.py` should:

1. load base schema;
2. load one domain schema;
3. apply allowed traits;
4. apply concrete capsule manifest;
5. reject conflicts;
6. enforce max inheritance depth;
7. emit flattened effective contract;
8. hash effective contract;
9. update reverse-dependency metadata.

The resulting effective contract is what runtime code and LLM tools consume.

---

# 21. Registry validator responsibilities

`validate_registry.py` should fail if:

- duplicate capsule IDs exist;
- unknown domain/composition/role appears;
- atomic capsule declares composite-only semantics;
- composite capsule duplicates an upstream implementation;
- unknown edge type appears;
- dependency target is missing;
- forbidden circular dependency exists;
- multiple behavior inheritance is attempted;
- inheritance depth > 2;
- a capsule's declared version is incompatible with upstream version ranges;
- semantic inference appears in an atomic capsule forbidden-semantic list;
- generated files were manually treated as source of truth.

---

# 22. Cycle policy

Default: capsule dependency graph must be a DAG.

Allowed cycles should be extremely rare and only exist in metadata/reference relations that are excluded from execution/derivation ordering.

Classify edges:

```text
CAUSAL / DEPENDENCY EDGES -> must be acyclic
REFERENCE EDGES           -> cycles may be allowed
```

Examples of acyclic edges:

```text
REQUIRES
DERIVES_FROM
USES
CONTRIBUTES_TO
IMPLEMENTS
```

Possible cyclic-safe metadata edges:

```text
RELATED_TO
CONTRADICTS
```

Do not use one graph traversal rule for all edge types.

---

# 23. Graph projection

Each capsule is a node with stable ID.

```text
Node:
  capsule_id
  domain
  composition
  role
  capsule_version
  contract_hash
  status
```

Edges carry type and compatibility metadata.

```text
Edge:
  from
  type
  to
  version_range
  required
  confidence?      # semantic/research edges only when meaningful
  provenance?
```

Runtime instances should be a separate temporal layer, not mixed into the static concept graph.

---

# 24. Market semantic example

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
SEMANTIC.ATOMIC.PRICE_POSITION
SEMANTIC.ATOMIC.PRICE_RESPONSE
SEMANTIC.ATOMIC.RETAIL_FLOW
SEMANTIC.ATOMIC.INSTITUTION_FLOW
SEMANTIC.ATOMIC.ORDER_IMBALANCE
        |
        +--> SEMANTIC.COMPOSITE.ABSORPTION
        +--> SEMANTIC.COMPOSITE.RETAIL_PANIC
        +--> SEMANTIC.COMPOSITE.INSTITUTIONAL_CONFIDENCE
                     |
                     +--> SEMANTIC.COMPOSITE.PANIC_WITH_ABSORPTION
```

Temporal patterns remain separate:

```text
PANIC_WITH_ABSORPTION
  TEMPORALLY_PRECEDES
RECOVERY
```

A future Research domain may test whether that transition has predictive power, without polluting the semantic definition itself.

---

# 25. Execution example

```text
EXECUTION.ATOMIC.BROKER_CONNECTION
EXECUTION.ATOMIC.ACCOUNT_SNAPSHOT
EXECUTION.ATOMIC.ORDER_QUERY
EXECUTION.ATOMIC.POSITION_QUERY
EXECUTION.ATOMIC.ORDER_SUBMIT
          |
          +--> EXECUTION.COMPOSITE.PREPARE_ORDER
          +--> EXECUTION.COMPOSITE.ORDER_LIFECYCLE
```

`PREPARE_ORDER` should consume contracts from atomic capabilities rather than copy broker-specific logic.

---

# 26. LLM context bundles

Create a deterministic command:

```bash
capsule context <capsule_id>
```

It should package only:

```text
effective contract
manifest
implementation
unit tests
direct dependency manifests
direct dependent manifests
recent change receipts
relevant decisions
```

Optional:

```bash
capsule context <capsule_id> --depth 2
```

Never default to loading the whole graph.

---

# 27. Global rules that should become hard gates

1. **No anonymous dependencies.** Every dependency is typed.
2. **No deep inheritance.** Contract inheritance depth <= 2.
3. **No behavior multiple inheritance.** Use composition.
4. **No duplicated upstream logic in Composite capsules.**
5. **No hand-maintained global index.** Generate it.
6. **No concept identity tied to implementation.**
7. **No runtime instance confused with concept definition.**
8. **No breaking edit without impact report.**
9. **No semantic change without version bump.**
10. **No LLM full-repo review by default.** Use targeted context bundles.
11. **No graph edge without declared semantics.**
12. **No generated documentation as authoritative truth.**

---

# 28. Implementation order for the local LLM

## Phase A — Foundation only

Build before migrating many capsules:

```text
contracts/capsule.schema.json
contracts/execution.schema.json
contracts/semantic.schema.json
registry format
edge vocabulary
validator
contract compiler
reverse dependency builder
impact command
context command
change receipt format
```

Acceptance criteria:

- 2 Execution Atomic examples
- 1 Execution Composite example
- 3 Semantic Atomic examples
- 1 Semantic Composite example
- validator detects intentional bad fixtures
- impact tool returns only the relevant subgraph
- effective contracts are deterministic

## Phase B — Existing capsule migration

Migrate existing functional capsules to the new registry without changing their behavior.

Do not refactor business logic during migration unless required by the contract boundary.

## Phase C — Semantic capsules

Add initial semantic market concepts:

```text
VolumeActivity
PricePosition
PriceResponse
RetailFlow
InstitutionFlow
OrderImbalance
Persistence
```

Then Composite concepts:

```text
Absorption
RetailPanic
InstitutionalConfidence
```

## Phase D — Graph UI

Only after the registry and graph are trustworthy:

- spatial graph view
- zoom/pan
- filter by domain/composition/role
- dependency highlighting
- impact highlighting
- version/health badges
- recent run logs for Execution capsules
- semantic provenance inspection for Semantic capsules

The UI must visualize the graph; it must not become the graph's source of truth.

---

# 29. Definition of done for v1 foundation

Foundation v1 is done when:

```text
[ ] every capsule has a stable ID
[ ] domain/composition/role are orthogonal
[ ] shallow contract inheritance works
[ ] traits work without silent overrides
[ ] behavior composition is explicit
[ ] graph edges are typed
[ ] reverse dependency index is generated
[ ] impact analysis works
[ ] LLM context bundle works
[ ] effective contracts are compiled
[ ] hashes are deterministic
[ ] breaking changes invalidate only affected subgraphs
[ ] generated docs can be rebuilt from source truth
[ ] concept and implementation IDs are separate
[ ] definition and runtime instances are separate
[ ] atomic/composite invariants are validated
[ ] bad fixtures prove the gates actually block violations
```

---

# 30. Final architecture rule

> **Inheritance is for shared contract shape, not hidden behavior. Composition is for behavior and meaning. The graph records dependencies. Hashes and versions identify what changed. Impact analysis decides what must be reread or revalidated. Generated context bundles decide what an LLM is allowed to see by default.**

This is the mechanism that allows Capsule App Hub to scale from tens to thousands of capsules without forcing every model or developer to understand the entire repository for every local change.
