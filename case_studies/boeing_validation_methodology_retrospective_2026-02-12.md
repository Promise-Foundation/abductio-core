# ABDUCTIO Boeing Validation Retrospective (Through February 12, 2026)

## 1) Validation methodology we are trying to make work

This is the methodology stack we have been trying to operationalize and validate.

### 1.1 Core validation objective

We are not trying to show "always pick a winner." We are trying to show a stronger claim:

1. Mechanical correctness: the inference engine obeys strict method contracts.
2. Epistemic discipline: no unjustified confidence inflation; explicit handling of underdetermination.
3. Comparative value: method variants improve measurable quality (calibration, error, utility) under matched budget/scope/evidence.
4. Auditability and reproducibility: every run is reconstructible and versioned.

### 1.2 Canonical validation architecture

The validation approach has been organized into four tracks (documented in `/Users/davidjoseph/github/abductio-core/case_studies/unified_empirical_strategy.md`):

1. Invariant track (BDD + unit tests): executable method contract.
2. Synthetic/ablation track: isolate architectural effects.
3. Historical frozen-evidence track (AAIB staged backtests): realistic but leakage-controlled evaluation.
4. Decision-quality track: downstream utility/regret (planned/partial).

### 1.3 Boeing case protocol we have been using

For `Boeing_737-8AS_9H-QAA_12-25` we have been evaluating on staged historical packets:

- `T0_PRELIM`, `T1_EARLY`, `T2_INTERIM`, `T3_PREFINAL`
- Frozen evidence available at each stage (no hindsight leakage)
- Fixed hypothesis root set and strict-MECE settings when enabled
- Fixed credit budget (often 150 in recent runs)
- Metric family: top-1 accuracy, top-1/tie hit rate, mean Brier, mean log loss, abstention behavior, oracle-target mass, and stop reasons

### 1.4 Reproducibility and provenance controls

We added/used:

1. Frozen safe baselines (`/Users/davidjoseph/github/abductio-core/case_studies/safe_baseline.md`, `safe_baseline_v1.policy.json`, `safe_baseline_v2.policy.json`).
2. Policy fingerprints and run metadata in `run_meta.json`.
3. Staged backtest and ablation reports under `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/results/backtest/`.

---

## 2) Unsatisfactory Boeing results we have been getting

### 2.1 Main unsatisfactory pattern

Across completed Boeing runs, the persistent pattern has been:

1. Top root frequently/consistently = `H_UND`.
2. Top-1 accuracy remains `0.0` in key runs.
3. Oracle target root (`R1_PUSHBACK_PROCEDURAL_DEVIATION`) remains low mass relative to abstention.
4. Runs often end with `CREDITS_EXHAUSTED` before decision closure criteria are satisfied.

### 2.2 Key concrete run outcomes

#### A) Completed ablation with clean outputs

From `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/results/backtest/20260211T173104Z_ablation.json`:

- `baseline`: top1=0.0, mean_brier=0.87827243, abstention_rate=1.0
- `pair_engine`: top1=0.0, mean_brier=0.85345494, abstention_rate=1.0
- `dynamic_und`: top1=0.0, mean_brier=0.85741829, abstention_rate=1.0
- `composition`: top1=0.0, mean_brier=1.04032099, abstention_rate=1.0

Interpretation:

- Some calibration-like improvement (Brier) from pair adjudication variants.
- No winner recovery (top-1 accuracy still zero).
- Composition variant worsened Brier in this run.

#### B) Ablation run blocked by connectivity

From `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/results/backtest/20260211T175927Z_ablation.json`:

- All variants: `rows_ok=0`, `rows_error=4`.
- Error: API connection/DNS failure (`APIConnectionError ... ConnectError: [Errno 8] ...`).

Interpretation:

- No epistemic conclusion possible from that run.

#### C) Completed non-hardened backtest run

From `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/results/backtest/20260211T202225Z.json`:

- Stage aggregates (`T0..T3`) all have `top1_accuracy=0.0`.
- `top_root_id` = `H_UND` at all four stages.
- `mean_oracle_target_p` about `0.093` to `0.118`.
- `mean_top_root_p` about `0.473` to `0.485`.
- `stop_reason` = `CREDITS_EXHAUSTED` in all stage rows.

Interpretation:

- Strong underdetermination dominates final ranking.

#### D) Partial hardened-one-shot run artifacts (interrupted before full report)

From run directories:

- `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/cases/Boeing_737-8AS_9H-QAA_12-25/runs/abductio/20260211T204209Z--hist_t0_prelim`
- `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/cases/Boeing_737-8AS_9H-QAA_12-25/runs/abductio/20260211T210133Z--hist_t1_early`
- `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/cases/Boeing_737-8AS_9H-QAA_12-25/runs/abductio/20260211T213146Z--hist_t2_interim`

Observed in those partial runs:

- Pair adjudication queue was active (`PAIR_ADJUDICATION_TARGET_SELECTED` counts ~10-11 per stage).
- Top root still `H_UND`.
- `H_UND` mass lower than non-hardened run (~0.204 to ~0.234 in partial hardened vs ~0.473 in non-hardened completed run).
- Oracle root mass increased (roughly ~0.139 to ~0.189 in partial hardened stages).
- Still ended with `CREDITS_EXHAUSTED`.

Interpretation:

- Mechanism engagement improved (queue actually active).
- Some directional improvement in mass allocation.
- Still no decisive winner recovery in completed evidence.

### 2.3 Specific bug we did identify and fix

In older composition runs, selected pair tasks could be misapplied.

Example run: `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/cases/Boeing_737-8AS_9H-QAA_12-25/runs/abductio/20260211T173104Z--hist_composition_t3_prefinal`

- Found `PAIR_ADJUDICATION_TARGET_SELECTED` events where the target pair differed from the pair actually applied in contrastive context.
- Example: `target_pair_applied=False` while target pair key was non-empty.

This is now fixed and covered by a dedicated BDD feature (`41_pair_target_binding_outside_global_catalog.feature`).

---

## 3) Everything we tried while updating methodology together

Below is the full step ledger of methodology/implementation moves we introduced, what each was intended to achieve, and whether it actually helped.

Legend:

- Helped (mechanical): improved correctness/contract compliance in tests.
- Helped (empirical): improved Boeing outcome metrics.
- No clear help yet: not yet measured cleanly or no observed Boeing gain.

### 3.1 Process and evaluation infrastructure steps

| Step | What we changed | Intended outcome | Did it help? |
| --- | --- | --- | --- |
| 1 | Built case-study pipeline with report/version provenance (`aaib_bench` pipeline/backtest outputs, run metadata, fingerprints) | Reproducible, auditable runs | Helped (mechanical): yes |
| 2 | Added frozen baseline profiles (`safe_baseline_v1`, `safe_baseline_v2`) | Stable comparison anchor, avoid moving target | Helped (mechanical): yes |
| 3 | Added unified empirical strategy docs (`unified_empirical_strategy.md`, `validation_overview.md`, reviewer guidance) | Shared validation standard across experiments | Helped (method governance): yes |
| 4 | Repeated staged historical backtests and ablations on Boeing | Empirical feedback loop while changing method | Helped (learning): yes; outcome still unsatisfactory |
| 5 | Updated white/yellow papers to align with stricter contrastive and certification semantics | Theory-implementation alignment | Helped (normative alignment): yes |

### 3.2 Core methodological hardening steps (feature-by-feature)

These correspond to executable BDD features in `/Users/davidjoseph/github/abductio-core/tests/bdd/features/`.

| Step | Artifact | Intended achievement | Observed status |
| --- | --- | --- | --- |
| 6 | `12_parent_k_propagation.feature` | Proper recursive confidence propagation from children to parent | Helped (mechanical): yes |
| 7 | `13_evidence_search.feature` | Make search credit-metered and auditable | Helped (mechanical): yes |
| 8 | `14_mece_certificate_gate.feature` | Enforce strict MECE prerequisites | Helped (mechanical): yes |
| 9 | `15_contrastive_reasoning_conformance.feature` | Bound non-discriminative drift; enforce contradiction penalties | Helped (mechanical): yes |
| 10 | `16_simple_claim_interface.feature` | Add easy interface for user-supplied claims | Helped (usability): yes; not a Boeing fix by itself |
| 11 | `17_frame_and_calibration_hardening.feature` | Prevent confidence inflation in weakly framed tasks | Helped (mechanical): yes |
| 12 | `18_closure_and_contrastive_hardening.feature` | Tougher closure semantics for decision safety | Helped (mechanical): yes |
| 13 | `19_dependency_penalty_hardening.feature` | Penalize shared-source/shared-assumption overcounting | Helped (mechanical): yes |
| 14 | `20_mode_and_stop_semantics_hardening.feature` | Separate explore/certify semantics; safer stopping behavior | Helped (mechanical): yes |
| 15 | `21_next_step_guidance.feature` | Actionable output under epistemic exhaustion | Helped (diagnostics): yes |
| 16 | `22_domain_profile_induction_and_policy_binding.feature` | Improve unseen-domain policy bootstrap | Helped (mechanical): yes |
| 17 | `23_contrastive_adjudication_and_und_certification.feature` | Prevent default dumping into `H_UND` without adjudication logic | Helped (mechanical): yes; empirical bottleneck remained |
| 18 | `24_process_tracing_and_cross_domain_release_gates.feature` | Add release gates for strong claims | Helped (governance): yes |
| 19 | `25_one_shot_decision_contract_enforcement.feature` | Formalize one-shot decision constraints | Helped (mechanical): yes |
| 20 | `26_contrastive_evaluator_contract.feature` | Strong typed discriminator interface to evaluator | Helped (mechanical): yes |
| 21 | `27_active_set_decision_certification.feature` | Limit strict certification to active contenders | Helped (mechanical): yes |
| 22 | `28_contender_space_semantics.feature` | Explicit singleton vs compositional contender semantics | Helped (mechanical): yes |
| 23 | `29_contrastive_evidence_typing_contract.feature` | Require typed evidence in strict contrastive mode | Helped (mechanical): yes |
| 24 | `30_active_set_adjudication_closure_enforcement.feature` | Block closure until active-set adjudication is complete | Helped (mechanical): yes |
| 25 | `31_pair_adjudication_queue.feature` | Spend credits on unresolved pair discrimination tasks | Helped (mechanical): yes; empirical partial gain in Brier, no top-1 gain |
| 26 | `32_dynamic_abstention_mass.feature` | Replace fixed `H_UND` floor with pressure-sensitive abstention | Helped (mechanical): yes; empirical partial gain, still abstention-dominant |
| 27 | `33_compositional_story_expansion.feature` | Allow multi-factor causal stories (cardinality-limited) | Mixed: mechanical yes; Boeing ablation variant worsened Brier in observed run |
| 28 | `34_budget_feasible_pair_adjudication.feature` | Budget-feasible pair scope and honest coverage denominator | Helped (mechanical): yes; introduced a later-discovered edge case with pruning |
| 29 | `35_pair_adjudication_balanced_targeting.feature` | Avoid one-sided pair probing | Helped (mechanical): yes |
| 30 | `36_active_set_churn_accounting.feature` | Preserve unresolved-pair work continuity across active-set churn | Helped (mechanical): yes |
| 31 | `37_quote_fidelity_discriminator_gate.feature` | Protect typed evidence logic from quote-format noise | Helped (mechanical): yes |
| 32 | `38_evidence_discrimination_tag_mode.feature` | Tag-mode control for strictness (targeted vs exhaustive) | Helped (mechanical): yes |
| 33 | `39_counterevidence_credit_reservation.feature` | Reserve probe credits for counterevidence/falsification work | Helped (mechanical): yes; no decisive Boeing win yet |
| 34 | `40_pair_target_context_binding.feature` | Ensure selected pair overrides default pair in context | Helped (mechanical): yes |
| 35 | `41_pair_target_binding_outside_global_catalog.feature` | Fix bug where selected pair was absent after global pruning | Helped (mechanical): yes; empirical impact still needs clean completed hardened run |

Current verification status:

- Boeing-relevant BDD subset (`31` through `41`) currently passes end-to-end.
- Unit/branch stop-reason tests used during these changes also passed when run.

### 3.3 Boeing-specific empirical rerun and debugging steps

| Step | What we did | Intended effect | What happened |
| --- | --- | --- | --- |
| 36 | Ran staged ablation suite (`baseline/pair_engine/dynamic_und/composition`) | Identify which mechanism actually improves Boeing metrics | Partial help: Brier improved for pair variants; top-1 still zero |
| 37 | Investigated queue/context mismatch in composition T3 audit trace | Detect whether queue work was actually being spent on intended pair | Found real bug (`target_pair_applied=False` despite target pair selection) |
| 38 | Implemented authoritative target-pair binding in contrastive context (`run_session.py`) | Remove false coverage progress and restore pair-task fidelity | Fixed in BDD; audit now consistent in tested scenarios |
| 39 | Re-ran non-hardened backtest (`20260211T202225Z`) | Check if overall inference outcome changed | No: still `H_UND` top at all stages, top1=0.0 |
| 40 | Started hardened-one-shot long run (safe_baseline_v2 policy profile) | Force use of stricter pair/counterevidence machinery in Boeing | Partial stage outputs show mechanism engagement and lower `H_UND`, but run was interrupted before full report completion |
| 41 | Diagnosed apparent freeze reports | Determine if engine stuck vs just slow | Mostly long LLM-runtime behavior plus interruptions; not an internal deadlock proven |

### 3.4 Net effect so far

What clearly improved:

1. Methodological rigor and traceability improved substantially.
2. Many previously implicit reasoning rules are now executable and audited.
3. We fixed at least one concrete inference wiring bug in pair-target propagation.
4. Hardened partial runs show directional improvement in mass allocation (lower `H_UND`, higher oracle-root mass) when those mechanisms are active.

What is still unsatisfactory:

1. Completed Boeing evaluation still does not recover the oracle top root.
2. `H_UND` still dominates in completed runs.
3. Credits are exhausted before closure requirements are met.
4. Some variants (notably composition in one ablation) degraded calibration.

### 3.5 Honest bottom-line assessment as of this document

1. We have made major progress in *validity of process*.
2. We have not yet demonstrated robust *Boeing outcome success*.
3. The project has moved from "unreliable/internally inconsistent in places" toward "internally coherent but still underpowered on this hard historical case under current budget/evidence regime." 
4. The next decisive step is a clean, uninterrupted hardened full staged run (T0-T3) plus side-by-side comparison against the non-hardened completed run, using exactly the same frozen packets and budget.

