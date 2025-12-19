Architectural specifications
1) Layer boundaries and allowed dependencies

Domain (pure)

Contains: entities/value objects, deterministic policies, invariants, math, canonicalization rules, scheduling rules, aggregation rules.

Must not import: infrastructure, presentation, any LLM tooling.

Allowed imports: stdlib only (and possibly dataclasses, typing, decimal if you decide).

Application (orchestration)

Contains: use cases, DTOs, ports (interfaces), transaction boundaries (even if “in-memory”), error mapping.

Imports: domain + ports; never imports presentation.

Exposes: a stable “library surface” for external users + test step defs.

Infrastructure (adapters)

Implements ports: evaluator adapters (LLM/human), decomposer adapters, persistence, audit sinks, config loading.

Must not contain domain rules (only translation + IO + integration concerns).

Presentation (CLI/API)

CLI / FastAPI endpoints / JSON schema mapping.

Must be thin: parse input → call application → render output.

No domain rules, no scheduling logic, no math.

Hard rule: step definitions import only from application.
So application must offer test-friendly entrypoints and “testing doubles” to avoid step defs reaching down into domain.

2) Canonical “library surface” (application API)

Expose one primary use case, plus a couple of helpers:

RunSession(request: SessionRequest, deps: SessionDeps) -> SessionResult

Where:

SessionRequest includes: claim text, roots (statements + exclusion clauses), config, evidence bundle (optional), credits.

SessionDeps includes ports: Evaluator, Decomposer, AuditSink, and optionally Clock/UUIDProvider (for determinism control).

SessionResult includes: final hypothesis set (ledger + tree snapshots), stop reason, credits remaining, audit trace metadata.

Also expose:

ReplaySession(audit_trace) -> SessionResult (or similar) for deterministic replay tests.

ValidateHypothesisSet(roots) -> ValidationReport to surface anti-vagueness and “standalone hypothesis” issues early.

Key discipline: the use case should be the only thing CLI/API calls.

3) Domain model (minimal but sufficient)

Recommended minimum domain objects (names flexible):

HypothesisId, NodeId (opaque string types)

CanonicalId policy: canonical_id = sha256(normalize(statement))

RootHypothesis (id, statement, exclusion_clause, p_ledger, k_root, obligations map, status, credits_spent)

Node (id, statement, role NEC/EVID, p, k, rubric, children, decomp_type, or_mode, coupling, status, credits_spent, evidence refs)

HypothesisSet (roots map including H_other)

Config (tau, epsilon, gamma, alpha, max_children, coupling buckets, conservative delta, max_depth)

AuditEvent (typed event stream with deterministic numeric payloads)

Domain services/policies (pure functions):

initialize_hypothesis_set(request) -> HypothesisSet

select_leader_and_frontier(hset, config) -> frontier

canonical_order(roots_or_nodes) -> ordered list

choose_operation(frontier_root_state) -> Operation

apply_decomposition(hset, target, decomp_result) -> hset

apply_evaluation(hset, target, eval_result, config) -> hset

aggregate_slot(node, config) -> (p, k)

compute_multiplier(root) -> m

compute_p_prop(p_base, m) -> p_prop

apply_damping(p_current, p_prop, alpha) -> p_new

enforce_other_absorber(hset) -> hset

stop_check(state) -> StopReason|None

4) Ports (application-owned interfaces)

Define in application/ports:

Evaluator.evaluate(node: NodeSnapshot, evidence: EvidenceBundle) -> EvaluationOutcome

Decomposer.decompose(target: TargetSpec) -> DecompositionOutcome

AuditSink.append(event: AuditEvent) -> None

Testing doubles live in application/testing:

DeterministicEvaluator(outcomes_map)

DeterministicDecomposer(scripted_decompositions)

InMemoryAuditSink()

This ensures BDD step defs never touch domain.

5) Determinism as a first-class requirement

Determinism is the main “gotcha” in ABDUCTIO MVP.

Rules to enforce early:

All ordering uses canonical IDs from normalized text; never Python dict insertion order.

All ties broken by canonical ID.

No randomness unless injected via an interface with deterministic default (and turned off in tests).

Numeric stability: choose one approach and stick to it:

simplest: float + strict rounding in audit (e.g., store full precision + comparisons with tolerance)

safer: Decimal for ledger arithmetic (slower but clearer); if you go Decimal, do it from day 1.

Audit replay will catch almost all determinism regressions if implemented early.

Implementation plan and feature development order

The sequencing below matches “build the spine first, then add complexity,” and prevents the usual pitfalls (nondeterminism, audit gaps, layer leakage).

Milestone 0 — Project skeleton + “layer firewall”

Goal: enforce architecture before writing logic.

Deliverables:

Package layout: domain/, application/, infrastructure/, presentation/.

application/use_cases/run_session.py exists but can be stub.

CI checks:

import rules: e.g., simple script that fails if presentation imports domain directly, or if domain imports anything outside stdlib.

run Behave tests (even if empty initially).

Pitfalls prevented:

accidental layer coupling early (hard to unwind later)

Milestone 1 — Initialization + MECE ledger invariants + canonical IDs

Implement first because everything depends on correct MECE bookkeeping.

Features to complete (from your suite):

Session bootstrap and MECE initialization

Canonical IDs stable

Other absorber invariant enforcement routine

Implementation steps:

Domain: normalize_text, canonical_id.

Domain: initialize roots + H_other, set priors using gamma.

Domain: enforce_other_absorber and “repair corrupted ledger” path.

Application: RunSession supports “start session only” (credits can be 0).

Audit: emit init events + invariant check events.

Pitfalls prevented:

quietly drifting sum-to-one

order-dependent behavior baked in from day one

Milestone 2 — Obligation template scoping + anti-vagueness capping

Second because “SCOPED/UNSCOPED” drives scheduling and stopping.

Features:

Obligation template parity and scoping

Root cannot be scoped → UNSCOPED and k capped

Implementation steps:

Domain: template spec (required slots) as config or policy.

Decompose-root behavior: instantiate slot nodes (NEC) with p=1.0, k=0.15.

If decomposer fails → mark UNSCOPED and cap k_root <= 0.40 (and slot caps if applicable).

Audit events for: scoping attempt, success/failure, cap applied.

Pitfalls prevented:

“winning by labels” loophole

inconsistent slot sets across roots (kills permutation invariance)

Milestone 3 — Cost model + operation ledger + stop reasons

Third because you need a tight “engine loop” before evaluator math.

Features:

Only two ops exist, each costs 1 credit

Stop condition A/B/C behavior

Audit includes operation records with credit deltas

Implementation steps:

Domain: Operation type with DECOMPOSE / EVALUATE.

Application: run loop with credits decrement and stop checks.

Domain: deterministic choose_operation (even if evaluation/decomposition results are trivial at first).

Audit: operation events are emitted regardless of outcome.

Pitfalls prevented:

“extra hidden operations” creeping in (common with agent-y systems)

untestable loops

Milestone 4 — No-free-probability semantics (neutral NEC defaults) + basic aggregation

Do this before evaluation because it defines how decompositions affect multipliers.

Features:

Scoping alone doesn’t change ledger

Adding unassessed NEC children doesn’t penalize

Slot aggregation treats unassessed NEC as p=1.0

Implementation steps:

Domain: compute slot p from children with unassessed treated as 1.0.

Ensure ledger updates only happen after evaluation (or after you explicitly compute p_prop).

Audit: log the computed multiplier pieces even if they equal 1.0.

Pitfalls prevented:

“conjunction crushing by listing” (your core design target)

decomposer accidentally changing credence

Milestone 5 — Evaluator contract + k rubric mapping + conservative delta rule

Now you can safely start changing slot p and k.

Features:

Rubric mapping A–D → k, plus guardrail cap

Conservative |Δp|<=0.05 when evidence_refs empty

Root k_root derived conservatively (min of assessed NEC slots, plus UNSCOPED cap)

Implementation steps:

Domain: derive_k(rubric) mapping and guardrail.

Domain: apply_evaluation clamps p to [0,1], applies conservative delta rule.

Domain: recompute_root_k policy.

Application: evaluator port called only in EVALUATE op; store outcome into node and audit.

Pitfalls prevented:

evaluator accidentally “teleporting” beliefs without evidence

inconsistent k behavior across nodes/roots

Milestone 6 — Ledger update: multiplier → p_prop → damping → Other absorber

This is the heart of the algorithm’s credence movement.

Features:

Compute multiplier across template slots

p_prop computation and damped update with alpha

Other absorber enforcement logged

Implementation steps:

Domain: compute m_i = Π slot_p and p_prop = p_base * m_i.

define clearly what p_base is (usually current p_ledger at time of update; if you mean “at time of scoping,” persist it explicitly).

Apply damping per root update and enforce absorber invariant.

Audit: include every numeric value used.

Pitfalls prevented:

subtle differences between “base” definitions that break replay/invariance

floating drift that makes sum-to-one flaky

Milestone 7 — Deterministic scheduling + frontier selection + round-robin cycles

Only after the math works should you “optimize fairness.”

Features:

Frontier defined from leader and epsilon

Canonical iteration order

Tie-breaking by canonical ID only

Implementation steps:

Domain: leader = argmax(p_ledger) with canonical tie-break.

Domain: frontier = {h: p>=p_leader-epsilon}.

Domain: per-root operation choice policy (UNSCOPED → DECOMPOSE; missing slots → DECOMPOSE; else lowest-k slot etc.).

Application: cycle loop: for each root in canonical order, perform exactly one op.

Pitfalls prevented:

“focal injection” reappearing via UI conveniences

order dependence from dict iteration

Milestone 8 — Soft-AND coupling buckets (inside-slot AND)

Add once basic slot aggregation is stable.

Features:

Soft-AND formula with coupling buckets

Unassessed treated as 1.0 still

Implementation steps:

Domain: implement soft_and(children_p, coupling).

Ensure decomposition outcome carries decomp_type, or_mode, coupling.

Audit: record p_min, p_prod, c, result.

Pitfalls prevented:

silently changing aggregation semantics later

confusion between “slot product” vs “child soft-and”

Milestone 9 — End-to-end permutation invariance + replay

This is your “maturity gate.”

Features:

End-to-end invariance under input permutation

Replay reproduces identical final ledger

Implementation steps:

Make sure every tie break uses canonical ID.

Ensure audit includes enough to replay (or record the operations and outcomes precisely).

Implement ReplaySession that uses audit outcomes rather than ports.

Pitfalls prevented:

“it usually works” but fails in production ordering

debugging nightmares (audit replay becomes your superpower)

Milestone 10 — Infrastructure + presentation adapters (CLI/API)

Only after the engine is rock-solid.

Features:

CLI calls application use case

API calls application use case

No layer bypass

Implementation steps:

Infrastructure: implement real evaluator/decomposer adapters (LLM/human), audit sinks (JSONL), persistence if needed.

Presentation: CLI with click/argparse; API with FastAPI.

Contract tests ensure adapters call application once and only once, and outputs are derived from SessionResult.

Pitfalls prevented:

adapter logic duplicating domain rules

“two engines” (one in CLI, one in library)

Anticipated pitfalls and concrete preventions
Pitfall: “p_base” ambiguity causes drift and breaks audit replay

Prevention: define p_base explicitly as either:

Option A: always the current p_ledger at the moment of update (simplest, most local), or

Option B: a stored “scoping baseline” frozen at the time a root becomes SCOPED (requires storing p_base_at_scope).
Pick one early and write it into the domain policy + audit.

Pitfall: Python dict ordering sneaks into determinism

Prevention: never iterate dicts without sorting by canonical ID; store children/roots in dicts but expose iteration via domain policy functions that return ordered lists.

Pitfall: floating point noise breaks “sum to 1” assertions and replay

Prevention: decide now:

either use Decimal for ledger computations, or

enforce rounding strategy in domain and store audit numbers at that precision.
Also: write invariant checks with tolerances but keep audit replay using the exact stored numbers.

Pitfall: step defs start importing domain because it’s “easier”

Prevention: put all test harnesses in application/testing (builders, snapshot query helpers, deterministic doubles). Make it strictly more convenient than touching domain directly.

Pitfall: evaluator/decomposer contract not enforced consistently

Prevention: enforce contract in domain/application:

clamp p, enforce conservative delta rule, cap k as specified

validate decomposition child counts, roles, max_depth, etc.

all violations become explicit SessionErrors with audit events.

Pitfall: OR nodes accidentally inflate probability

Prevention: make OR aggregation for NEC explicit and conservative:

for NEC OR inside a slot, define it clearly (e.g., max of assessed children; unassessed = neutral)

forbid using EVID nodes to increase ledger directly (only attach to audit/explanations unless you later add explicit policy)

Pitfall: audit becomes “logs” rather than “replayable evidence”

Prevention: treat audit as an event-sourced stream with typed payloads:

every calculation step recorded with inputs + outputs

replay uses those payloads, not recomputation

Recommended “feature gating” rule

Do not start the next milestone until:

all features for the milestone pass,

invariance checks pass,

replay passes (from Milestone 9 onward),

architecture import firewall still passes.
