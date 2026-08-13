# Capsule Architecture Foundation v2

> Goal: establish an application-agnostic Capsule Hub that can grow to thousands of functional, semantic, and research capsules without forcing an LLM to reread or rewrite the whole corpus.
>
> Core rule: **Applications use Capsules. Capsules do not belong to Applications.**
>
> Core engineering principle: **inherit contracts shallowly, compose behavior explicitly, register typed relationships, generate views, and propagate invalidation only through the affected dependency subgraph.**

---

# 0. Architectural correction

The Capsule Hub must not be implemented as a subsystem of AceRail or any other application.

AceRail, feature-algebra, research engines, browser agents, recording systems, investigation systems, and future applications are external providers and/or consumers of Capsules.

The ownership direction is:

```text
                    CAPSULE HUB
                        │
        ┌───────────────┼────────────────┐
        │               │                │
    EXECUTION         SEMANTIC         RESEARCH
        │               │                │
        ▼               ▼                ▼
     AceRail       feature-algebra   research engine
   other apps       other engines     other labs
```

Not:

```text
AceRail
  └── Capsule Hub
```

This separation is mandatory because the Hub is intended to become a reusable graph/knowledge infrastructure across many domains.

---

# 1. System boundary

The independent Capsule Hub owns only generic infrastructure:

```text
identity
manifest
contract
registry
typed graph
versioning
provenance
provider bindings
runtime metadata
impact analysis
context bundle generation
change receipts
validation
generic UI metadata
```

The Kernel must not contain business-specific knowledge such as:

```text
broker
stock
market
portfolio
microphone
browser
investigation case
```

Those belong to domain capsules, providers, or applications.

Recommended independent repository boundary:

```text
capsule-hub/
├── kernel/
│   ├── schema/
│   ├── registry/
│   ├── graph/
│   ├── compiler/
│   ├── impact/
│   ├── context/
│   ├── receipts/
│   └── validation/
├── domains/
│   ├── execution/
│   ├── semantic/
│   └── research/
├── adapters/
│   ├── acerail/
│   ├── feature_algebra/
│   └── research_engine/
├── capsules/
│   ├── execution/
│   ├── semantic/
│   └── research/
├── runtime/
├── api/
├── ui/
├── tests/
└── docs/
```

---

# 2. Capsule taxonomy uses orthogonal axes

Do not create a giant inheritance tree for every capsule type.

Every Capsule is classified with orthogonal metadata.

## 2.1 Domain

```text
EXECUTION   executable capability / operation
SEMANTIC    observation / metric / concept / state / event / relation
RESEARCH    research atom / recipe / hypothesis / experiment / evidence / result
```

Future domains must be addable without rewriting existing capsule manifests.

## 2.2 Composition

```text
ATOMIC      smallest unit that preserves the intended capability or meaning
COMPOSITE   explicitly combines/references other capsules
```

Atomic/Composite is a structural property, not a license to duplicate implementation.

## 2.3 Role

Role is metadata and may be domain-specific.

Examples:

```text
EXECUTION:
SOURCE
QUERY
CONNECTOR
TRANSFORM
GATE
VALIDATOR
ORCHESTRATOR
ACTUATOR
SINK
MONITOR

SEMANTIC:
OBSERVATION
METRIC
CONCEPT
STATE
EVENT
RELATION

RESEARCH:
ATOM
RECIPE
HYPOTHESIS
EXPERIMENT
EVIDENCE
RESULT
REFUTATION
```

Do not turn every role into a Python subclass.

---

# 3. Class-like reuse without fragile inheritance

The system should support class-like reuse, but must avoid deep behavioral inheritance.

## 3.1 Allowed inheritance

Only shared contract/schema structure may be inherited.

Example:

```text
CapsuleContract
  └── SemanticContract
```

Recommended hard limit:

```text
MAX_CONTRACT_INHERITANCE_DEPTH = 2
```

## 3.2 Forbidden inheritance

Do not build:

```text
CapsuleBase
  -> SemanticCapsule
    -> MarketCapsule
      -> SentimentCapsule
        -> FearCapsule
          -> RetailPanicCapsule
```

Do not use multiple behavioral inheritance such as:

```text
class RetailPanic(VolumeActivity, RetailFlow, PriceResponse, Persistence)
```

This creates hidden coupling and a fragile-base-class problem.

## 3.3 Behavior is composition

Correct representation:

```text
RetailPanic
  DERIVES_FROM -> RetailFlow
  DERIVES_FROM -> PriceResponse
  CONTRIBUTED_BY -> VolumeActivity
  CONTRIBUTED_BY -> Persistence
```

The graph must make dependencies explicit.

---

# 4. Traits for cross-cutting reuse

Cross-cutting capabilities use deterministic traits rather than multiple inheritance.

Examples:

```text
PROVENANCE_V1
RUN_LOG_V1
HEALTH_STATUS_V1
CONFIDENCE_OUTPUT_V1
RUNTIME_STATUS_V1
```

Example manifest fragment:

```yaml
traits:
  - PROVENANCE_V1
  - RUN_LOG_V1
```

Rules:

1. traits cannot override capsule identity;
2. traits cannot silently redefine a field;
3. conflicts fail compilation;
4. traits are versioned;
5. trait changes participate in reverse-impact analysis.

---

# 5. Stable Capsule identity is separate from implementation

A semantic concept must remain stable even when the algorithm changes.

Example:

```text
Capsule identity:
SEMANTIC.ATOMIC.VOLUME_ACTIVITY

Implementations:
feature-algebra:F010-v1
feature-algebra:volume-activity-v2
polars:volume-activity-v3
```

Graph:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
  IMPLEMENTED_BY -> feature-algebra:F010-v1
  IMPLEMENTED_BY -> feature-algebra:volume-activity-v2
```

Separate at least:

```text
schema_version
contract_version
semantic_version
implementation_version
trait_version
```

Never overload one version number for all of them.

---

# 6. Providers and consumers

Applications and engines integrate through adapters.

## 6.1 AceRail

AceRail's current capsules remain owned by AceRail's existing execution architecture.

Do not modify AceRail's manifest schema merely to make the Hub support SEMANTIC or RESEARCH domains.

Instead:

```text
adapters/acerail/
```

maps existing AceRail fields into the Hub's generic model.

Preserve AceRail's existing architecture invariants, including automatically derived composition/kind and its capability audit guards.

Example:

```text
Hub node:
EXECUTION.ATOMIC.BROKER_ACCOUNT_QUERY

PROVIDED_BY -> AceRail
SOURCE_REF  -> existing AceRail capsule manifest
```

## 6.2 feature-algebra

feature-algebra remains a computation/feature provider, not the Capsule Registry.

Example:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
  IMPLEMENTED_BY -> feature-algebra:F010
```

Do not move feature-algebra into AceRail.

## 6.3 Research engines

Research execution code may remain in an existing research engine.

The Hub owns stable identity, relationship, version, provenance, and research graph metadata.

Example:

```text
RESEARCH.COMPOSITE.HIGH_POSITION_VOLUME_EXPANSION
  EXECUTED_BY -> research-engine:R_VOL_001
```

---

# 7. Source of truth hierarchy

Critical structure must be machine-readable.

```text
contracts/          authoritative schemas
registry/           authoritative capsule manifests
relations/          authoritative typed edges
bindings/           provider/implementation bindings
receipts/           machine-readable changes
views/              generated human-readable documents
```

Canonical rule:

```text
machine-readable contract > generated documentation > prose commentary
```

README files must never be the only location where a critical dependency or semantic rule exists.

---

# 8. Base Hub manifest

A generic Hub manifest must remain small enough for a weak local LLM to understand.

Example:

```yaml
capsule_id: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
schema_version: 1
contract_version: 1.0.0
semantic_version: 1.0.0

domain: SEMANTIC
composition: ATOMIC
role: METRIC

contract:
  extends: contracts/semantic.schema.json

identity:
  stable: true

inputs:
  - market.volume

outputs:
  - activity_score
  - activity_percentile

forbidden_semantics:
  - PANIC
  - CONFIDENCE
  - ACCUMULATION
  - DISTRIBUTION

dependencies: []

providers:
  - provider: feature-algebra
    implementation_ref: F010

provenance:
  required: true
```

The Hub manifest is not required to be identical to the provider's native manifest.

Adapters perform the mapping.

---

# 9. Atomic and Composite invariant

Core invariant:

> **An Atomic Capsule is the smallest capability or concept that cannot be decomposed further without losing its intended responsibility or meaning. A Composite Capsule must build through declared Capsule references and must not secretly reimplement lower-level logic.**

For COMPOSITE capsules:

- dependencies must be declared;
- provenance must identify upstream capsules;
- duplicated implementations of upstream calculations are forbidden;
- raw-data access should be denied unless explicitly justified;
- dependency edges must be typed.

---

# 10. Semantic boundary

Atomic semantic capsules may describe observations and measurements but must not smuggle higher-level interpretations.

Example:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
  MAY OUTPUT:
  activity_score
  percentile
  zscore

  MUST NOT OUTPUT:
  PANIC
  CONFIDENCE
  EUPHORIA
  ACCUMULATION
  DISTRIBUTION
```

Higher-order interpretations belong to Composite semantic capsules and must retain provenance.

Example:

```text
VolumeActivity
+ PriceResponse
+ Persistence
    ↓
SEMANTIC.COMPOSITE.ABSORPTION
```

Even then, research evidence should be linked explicitly rather than implied.

---

# 11. Research is a first-class domain

Research artifacts must not be hidden inside semantic implementation code.

Research node types include:

```text
ATOM
RECIPE
HYPOTHESIS
EXPERIMENT
EVIDENCE
RESULT
REFUTATION
```

Example lineage:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
SEMANTIC.ATOMIC.PRICE_RESPONSE
        │
        ├── USED_BY ──>
        │
RESEARCH.COMPOSITE.HIGH_VOLUME_LOW_PRICE_RESPONSE
        │
        └── TESTS ──>
RESEARCH.HYPOTHESIS.ABSORPTION
        │
        ├── SUPPORTS / REFUTES / INCONCLUSIVE_FOR
        ▼
SEMANTIC.COMPOSITE.ABSORPTION
```

A semantic concept must not be promoted merely because an LLM invented a useful-sounding label.

---

# 12. Typed graph edges

Never store anonymous `A -> B` links.

Initial generic edge vocabulary:

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
PROVIDES
PROVIDED_BY
CONSUMES
VALIDATES
TESTS
SUPPORTS
REFUTES
INCONCLUSIVE_FOR
REFINES
TRIGGERS
TEMPORALLY_PRECEDES
REPLACES
DEPRECATED_BY
```

Relations must be machine-readable and independently versionable.

Example:

```yaml
from: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
type: CONTRIBUTES_TO
to: SEMANTIC.COMPOSITE.RETAIL_PANIC
introduced_in: 1.0.0
```

---

# 13. Effective contract compilation

Do not require an LLM to mentally resolve inheritance and traits.

Compile:

```text
Base contract
+ Domain contract
+ Traits
+ Capsule manifest
+ Provider binding constraints
```

into:

```text
.build/effective_contracts/<capsule_id>.json
```

An LLM modifying one Capsule should normally need only:

```text
1. effective contract
2. capsule manifest
3. active provider/implementation binding
4. direct dependencies
5. direct dependents
6. relevant tests
7. recent change receipts
8. relevant architecture decisions
```

It should not read the entire repository by default.

---

# 14. Reverse dependency graph and local impact analysis

This is a core scalability requirement.

A low-level edit must not cause a repository-wide reread.

Every contract and implementation receives a deterministic hash.

```text
contract_hash
semantic_hash
implementation_hash
relation_hash
```

Every dependent records what it was last validated against.

## 14.1 Change classes

```text
DOC_ONLY
PATCH
IMPLEMENTATION_ONLY
NON_BREAKING_CONTRACT
BREAKING_CONTRACT
SEMANTIC_CHANGE
RELATION_CHANGE
PROVIDER_BINDING_CHANGE
```

## 14.2 Default propagation

```text
DOC_ONLY
  -> no invalidation

IMPLEMENTATION_ONLY
  -> validate target implementation
  -> no semantic invalidation if effective contract and behavior tolerance remain valid

NON_BREAKING_CONTRACT
  -> inspect direct dependents
  -> stop if their effective contract is unchanged

BREAKING_CONTRACT
  -> invalidate direct dependents
  -> propagate only where downstream effective behavior/contract changes

SEMANTIC_CHANGE
  -> follow meaning-bearing edges through affected subgraph

RELATION_CHANGE
  -> validate affected graph neighborhood and composites

PROVIDER_BINDING_CHANGE
  -> validate provider compatibility; do not invalidate unrelated domains
```

No default `GLOBAL_RESCAN` is allowed.

---

# 15. LLM context bundle

The Hub must provide a deterministic command/API similar to:

```bash
capsule context SEMANTIC.ATOMIC.VOLUME_ACTIVITY
```

Expected bundle:

```text
TARGET
EFFECTIVE_CONTRACT
MANIFEST
ACTIVE_PROVIDER
DIRECT_DEPENDENCIES
DIRECT_DEPENDENTS
RELEVANT_TESTS
RECENT_CHANGE_RECEIPTS
RELEVANT_DECISIONS
```

Another command:

```bash
capsule impact SEMANTIC.ATOMIC.VOLUME_ACTIVITY
```

must return only the affected dependency subgraph.

The agent instruction should explicitly state:

> Do not search the whole repository unless the impact analyzer returns GLOBAL_IMPACT because the graph cannot resolve the dependency boundary.

`GLOBAL_IMPACT` should be treated as a degraded/error state, not normal operation.

---

# 16. Change receipts

Every material change produces a machine-readable receipt.

Example:

```yaml
change_id: CHG-2026-08-13-001
target: SEMANTIC.ATOMIC.VOLUME_ACTIVITY
change_class: IMPLEMENTATION_ONLY

before:
  contract_hash: ...
  semantic_hash: ...
  implementation_hash: ...

after:
  contract_hash: ...
  semantic_hash: ...
  implementation_hash: ...

affected_capsules:
  - RESEARCH.COMPOSITE.HIGH_POSITION_VOLUME_EXPANSION

not_affected:
  - EXECUTION.ATOMIC.BROKER_ACCOUNT_QUERY

validation:
  status: PASS
  tests: [...]
```

Change receipts become durable memory for later LLM sessions.

---

# 17. Documentation at scale

Do not maintain giant hand-written master documents.

Authoritative data:

```text
registry/*.yaml
relations/*.yaml
contracts/*.json
bindings/*.yaml
receipts/*.yaml
```

Generated views:

```text
views/README_INDEX.md
views/GRAPH.md
views/DOMAIN_EXECUTION.md
views/DOMAIN_SEMANTIC.md
views/DOMAIN_RESEARCH.md
views/IMPACT/*.md
```

Generated views may be deleted and rebuilt.

Optional Capsule-local prose may explain:

```text
meaning
non-meaning
examples
known limitations
```

It must not duplicate the authoritative contract.

---

# 18. Generic Capsule UI belongs to the Hub

The Hub may expose a generic UI independent from application-specific UIs.

Generic concepts include:

```text
zoomable canvas / graph workspace
capsule coordinates
row × column result tables
frozen headers
column visibility controls
runtime status text
health status
last three run logs
provider identity
input/output inspection
impact neighborhood
version/provenance inspection
```

AceRail may retain its own trading UI.

The generic Capsule UI must not become AceRail UI.

---

# 19. Definition vs runtime instance

Stable definition:

```text
SEMANTIC.COMPOSITE.RETAIL_PANIC
```

Runtime instances:

```text
RetailPanic @ T1
RetailPanic @ T2
RetailPanic @ T3
```

Do not create a new Capsule definition for each runtime observation.

Runtime instances belong in runtime storage, not primarily in Git.

They should record:

```text
capsule_id
contract_version
semantic_version
implementation/provider ref
as_of
input snapshot/provenance
output
confidence when applicable
upstream instance refs
```

---

# 20. Legacy migration rule

Existing application-local capsules do not need immediate destructive migration.

First integrate them through adapters.

Only migrate a provider's native schema when there is an independent provider-local reason to do so.

Therefore:

```text
Hub evolution != mandatory AceRail schema migration
Hub evolution != mandatory feature-algebra schema migration
```

This is a hard decoupling rule.

---

# 21. Foundation implementation order

Do not begin by registering hundreds of capsules.

Implement the foundation in this order:

```text
1. base schema
2. domain model
3. stable identity
4. version separation
5. trait mechanism
6. typed relation schema
7. registry
8. provider adapter interface
9. effective contract compiler
10. graph builder + reverse dependency index
11. impact analyzer
12. context bundle generator
13. change receipt writer
14. validator
15. generated views
16. minimal generic API/UI
```

Then integrate only small fixtures:

```text
AceRail execution capsules × 2
feature-algebra semantic atoms × 2
research recipe × 1
```

---

# 22. Required foundation acceptance tests

## Case A — semantic implementation change

Change the implementation of:

```text
SEMANTIC.ATOMIC.VOLUME_ACTIVITY
```

Expected:

```text
implementation_changed = true
semantic_changed = false
```

Only relevant semantic/research dependents are inspected.

AceRail's unrelated execution capsules must not be invalidated.

## Case B — AceRail broker implementation change

Change an AceRail broker provider implementation.

Expected:

```text
affected: relevant execution capsules
unaffected: VolumeActivity, PricePosition, unrelated research recipes
```

## Case C — semantic contract breaking change

Change a field required by a composite semantic capsule.

Expected:

```text
direct dependent invalidated
transitive propagation only where effective outputs/contracts change
```

No unconditional repository-wide scan.

## Case D — future domain addition

Add a fourth domain.

Existing domain manifests must remain valid without migration.

## Case E — provider replacement

Swap one implementation provider while preserving the effective contract.

Expected:

```text
provider_binding_changed = true
semantic identity unchanged
unrelated graph nodes unaffected
```

---

# 23. Architectural iron rules

1. **Applications use Capsules. Capsules do not belong to Applications.**
2. **The Hub Kernel must be application-agnostic.**
3. **Contract inheritance is shallow; behavior is composition.**
4. **No hidden behavioral multiple inheritance.**
5. **Atomic Capsules cannot smuggle composite semantics.**
6. **Composite Capsules cannot duplicate upstream logic.**
7. **Concept identity is distinct from implementation/provider identity.**
8. **Research claims are distinct from semantic definitions.**
9. **All important relationships are typed and machine-readable.**
10. **Impact propagation follows the dependency graph, not repository breadth.**
11. **Generated documentation is never the primary truth.**
12. **Legacy providers integrate through adapters before destructive migration is considered.**
13. **A weak local LLM must be able to modify one Capsule using a bounded context bundle.**
14. **GLOBAL_RESCAN is an error/degraded path, not the normal workflow.**

---

# 24. Immediate next milestone

Create or locate the independent `capsule-hub` repository and implement only the Foundation.

Do not yet mass-migrate AceRail capsules or research atoms.

The first milestone is successful only when all three can coexist in one Hub graph without sharing implementation schemas:

```text
AceRail execution provider
feature-algebra semantic provider
research engine provider
```

The key proof is not the number of Capsules. The proof is that a change in one provider/domain produces a precise local impact set and does not force an LLM to inspect unrelated files or applications.
