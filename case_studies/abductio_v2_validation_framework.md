# ABDUCTIO v2 Validation Framework - Integrated Change Set (Score Maximization)

This document is the canonical, single source of truth for ABDUCTIO v2 validation. It integrates the best elements of the second-opinion framework with additional protocols that increase defensibility, auditability, and reviewer confidence. All supporting documents should defer to this file for methodology, preregistration, ablations, metrics, and reporting requirements.

## 1) Scope and empirical claims

### 1.1 Six empirical claims (canonical)
1) Template parity (no structural advantage for a hypothesis by template design)
2) No-free-probability (probability changes only when credits are spent)
3) Symmetric updates (negative evidence can lower p; no one-way ratchets)
4) VOI-lite scheduling (credit allocation improves score-vs-credits)
5) (p,k) calibration (confidence aligns with score behavior)
6) Decision quality (actions under uncertainty improve expected utility)

### 1.2 Units of analysis
- Preferred: problem-level (case or scenario)
- Allowed only when necessary: node-level (explicitly justify)

### 1.3 Three data tiers
- Tier 1: synthetic
- Tier 2: historical
- Tier 3: live forecasting

### 1.4 Phase plan
- Phase 0: evaluator reliability + invariants (must pass before any claims)
- Phase 1 (Tier 1): Claims 2 and 4 with clean and stress oracles
- Phase 2 (Tier 2): Claims 5 (and optionally 2) with freeze/leakage gates + OS stratification
- Phase 3 (Tier 3): Claims 5 and 6 with strict evidence access logging

## 2) Preregistration requirements (review-proof)

### 2.1 For each claim, define
- Unit of analysis
- Stopping rule (choose exactly one for the primary analysis)
  - Fixed-credit (e.g., 20 credits per problem), or
  - Threshold (stop when a decision-quality threshold is met), with a maximum cap
- Primary dependent variable (exactly one) and up to two secondary DVs

### 2.2 Online Brier definition (replace vague targets)
- Target probability: p(true hypothesis) at the root (or the mapped label)
- Computation time: after each EVALUATE operation
- Multi-class Brier: sum over classes of (p_i - y_i)^2
- One-vs-rest Brier must be explicitly labeled and justified

### 2.3 Hierarchical analysis plan
- One primary test per claim; all else exploratory
- Mixed-effects modeling with problem and evaluator random effects
- Effect sizes + 95% CIs are primary evidence; p-values are secondary

### 2.4 Required prereg template (minimum fields)
- Claim ID and scope
- Unit of analysis
- Stopping rule and credit budget
- Primary DV and secondary DVs
- Hypothesized effect direction
- Inclusion/exclusion rules and time window
- Planned stratification and covariates (OS class, evidence quality tier)
- Statistical model and estimator
- Power analysis method and assumptions
- Multiple-comparisons strategy
- Data and code freeze date

## 3) Evidence freeze and leakage controls (Tier 2 mandatory)

### 3.1 Evidence Freeze Protocol (E_T)
Allowed:
- Factual header fields
- Factual narrative and observations
- Limited synopsis content if purely factual

Disallowed:
- Analysis
- Conclusion
- Safety actions

Redaction rules:
- Remove figures, footnotes, page numbers, and meta commentary
- Remove causal language and hindsight framing

### 3.2 Leakage Audit Report (required for every dataset build)
Report must include:
- Count of lines/items dropped by each rule
- Keyword hits (soft and hard gates)
- Artifact hashes for evidence packets
- Two-independent-builder agreement metrics (subset)

### 3.3 Oracle strength stratification
- Each historical case must have OS class
- Analyses are stratified by OS or include OS as a covariate
- Label-dependent metrics must be reported with OS context

## 4) Evaluator validity gates (Phase 0 prerequisite)

### 4.1 Consistency thresholds
- ICC(p) >= 0.70 for human evaluators
- ICC(p) >= 0.90 for deterministic LLM evaluators
- k-bucket agreement >= 70% exact or plus/minus 1 bucket

### 4.2 Matched evaluator calls
- For paired comparisons, same nodes must use identical evaluator outputs
- Log evaluator call IDs and reuse them across variants

### 4.3 Synthetic stress oracle
- Run Tier 1 with:
  1) Clean deterministic oracle
  2) Noisy or adversarial oracle (bias + variance + occasional rubric error)
- Report whether effects persist under stress

## 5) Operationalized constructs and core metrics

### 5.1 Evidence quality (choose one per tier)
- Tier 1 (synthetic): generative signal parameter (SNR) + noise settings
- Tier 2 (historical): evidence-item rubric with inter-rater agreement
- Tier 3 (live): source reliability tags + new information count

### 5.2 Unfair advantage and underspecification (numeric)
- Template compliance score: fraction of required obligation slots instantiated
- Obligation depth asymmetry: depth/coverage difference across hypotheses
- Free-mass gap: probability change without a paid EVALUATE

### 5.3 Robustness beyond ordering
- Equivalent Decomposition Robustness (EDR):
  - Same hypothesis expressed with logically equivalent decompositions
  - Success criterion: |p_variant_a - p_variant_b| <= epsilon at fixed credits

## 6) Ablation suite and credit accounting (standardized)

### 6.1 Stable ablation variants
- v2 (full system)
- NoTemplate (template parity removed)
- FreeDecomp (no-free-probability removed)
- MostLikely scheduler (VOI-lite replaced)
- Asym-Clipped (negative evidence clipped or thresholded)

### 6.2 Credit accounting model
- Enumerate credit-spending operations in config
- Enforce no-free-probability: decomposition is belief-neutral unless EVALUATE
- Automated invariants: sum-to-1, non-negativity, credit-boundedness

## 7) Claim-specific protocols (compatible and tight)

### 7.1 Claim 1: Template parity
- Primary DV: winner-flip rate conditioned on high asymmetry
- Secondary DV: correlation of p with compliance after controlling for evidence quality

### 7.2 Claim 2: No-free-probability
- Primary DV: correlation of p with decomposition depth controlling for evidence quality
- Secondary DV: Brier difference on decomposability-skew problems
- Diagnostic: free-mass gap

### 7.3 Claim 3: Symmetric updates
- Replace AsymOnly with Asym-Clipped or Asym-Thresholded
- Add time-to-crossover and regret vs credits

### 7.4 Claim 4: VOI-lite scheduling
- Pre-register priority function and tie-break rules
- Primary DV: AUC of score vs credits (Brier or log score)
- Secondary DV: fraction of early credits on ground-truth hypothesis

### 7.5 Claim 5: (p,k) calibration
- Pre-register k-bucket boundaries
- Primary DV: Brier monotonicity across k-buckets
- Secondary DV: inter-rater variance of p vs k
- Model: mixed-effects regression with evaluator + problem random effects

### 7.6 Claim 6: Decision quality
- Require a utility model:
  - actions
  - payoffs
  - optimality definition
- Prefer domains with objective resolution; expert-consensus datasets are separate

## 8) Results and reporting requirements

### 8.1 Results table per claim (mandatory)
For each claim, report:
- Primary effect (delta and 95% CI)
- Secondary effects
- Sensitivity checks (stress oracle, OS strata)
- Failure modes and nulls

### 8.2 Mandatory plots across claims
- Score vs credits curves
- Reliability diagrams faceted by k-bucket

### 8.3 Replication package (publishable)
- Data, code, prereg, deterministic run configs
- Full audit logs and hashes

## 9) Reproducibility checklist (required artifact)

Each run must include:
- Commit hash + config snapshot
- Evaluator spec: model/version/prompt, temperature, seeds
- Dataset provenance, freeze protocol, leakage audit
- Raw logs of credits spent per operation
- Decision traces and p/k updates

## 10) Power analysis (required in prereg)

Use one of the following:
- Simulation-based power with the planned mixed-effects model
- Analytical power for the primary DV if assumptions permit

Minimum requirements:
- Report expected effect size (delta) and its justification
- Report minimum detectable effect at target power (>= 0.80)
- Provide expected sample size at each tier

## 11) Minimal do-these-first list (highest ROI)

1) Phase 0 evaluator reliability + matched evaluator calls
2) Evidence Freeze Protocol + Leakage Audit for Tier 2
3) Operationalize evidence quality + unfairness metrics
4) Replace AsymOnly with Asym-Clipped; standardize variant suite
5) Pre-register one primary DV per claim + stopping rules
