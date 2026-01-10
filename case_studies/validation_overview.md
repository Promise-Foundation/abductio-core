# ABDUCTIO Case Study Validation Overview

## Purpose
This validation evaluates ABDUCTIO as a *responsible inference method* under real-world constraints. It does not treat agency findings as ground truth. Instead, it compares ABDUCTIO's state under frozen evidence to a later, better-resourced reference outcome, and scores both agreement and epistemic behavior (auditability, humility, robustness).

## ABDUCTIO v2 Validation Framework (Canonical)
This repo uses a single canonical validation framework:

- **Six empirical claims:** Template parity, No-free-probability, Symmetric updates, VOI-lite scheduling, (p,k) calibration, Decision quality.
- **Three tiers:** synthetic, historical, live forecasting.
- **Evaluator validity prerequisite:** ICC(p) >= 0.70 for human evaluators, ICC(p) >= 0.90 for deterministic LLM evaluators, and k-bucket agreement >= 70% exact or +/- 1 bucket.
- **Canonical doc:** `case_studies/abductio_v2_validation_framework.md`

## What This Evidence Represents
Case studies are built from public reports (e.g., AAIB bulletins). Each case has:
- A frozen evidence packet (what was knowable at a chosen time T).
- A later reference outcome (the agency's analysis/conclusion) used as an oracle, not Truth.
- A MECE hypothesis set scoped to a single question (S1 proximate cause or S2 preventable cause).

Evidence packets include factual header fields, narrative facts, and observations. Causal attributions and conclusions are held out and placed in the answer key.

## Evidence Packet Construction Protocol
Evidence packets follow `case_studies/data/UK_AAIB_Reports/spec/evidence_packet_protocol.md`:
- Allowed: observations, measurements, timings, and verbatim statements.
- Disallowed: causal attributions, report meta-commentary, and post-event safety actions.
- Extractors must achieve Cohen's kappa >= 0.70 on inclusion decisions.

## Core Assumptions
- **Oracle fallibility:** reference outcomes are fallible and are treated as later inference states.
- **Evidence freeze:** only information available by time T is allowed in the evidence packet.
- **Fairness contract:** identical scope, hypothesis roots, and budget model for all methods.
- **MECE discipline:** roots are mutually exclusive and collectively exhaustive for the chosen scope, with explicit exclusions and a defined "other/undetermined" policy.
- **Root set validation:** each root set is reviewed using `spec/root_set_validation.md`, including overlap scoring and completeness checks.
- **No hindsight leakage:** causal statements are excluded from evidence packets.
- **Auditability:** every update must be traceable to logged evidence and rubric scoring.

## How ABDUCTIO Is Used
1. **Define scope** (S1 or S2) for each case.
2. **Instantiate MECE roots** with exclusion clauses and an open-world policy if needed.
3. **Freeze evidence** into a packet (header facts + factual narrative).
4. **Run ABDUCTIO** under a fixed credit budget and deterministic scheduling.
5. **Log updates**: each EVALUATE operation logs p/k, rubric scores, evidence refs, and deltas.
6. **Compare** ABDUCTIO outputs to the reference outcome and compute metrics.

ABDUCTIO outputs are interpreted as *ledger allocations of credence* and confidence, not claims of truth.

## Metrics and What They Mean
- **Label-dependent (oracle agreement):** top-1/top-k, log score, Brier score.
- **Label-independent (responsibility):** audit reproducibility, uncertainty discipline, defeater awareness, robustness to ordering/decomposition, and appropriate mass on H_other.

Disagreement is categorized (D0-D4) and justified based on evidence references and confidence limits.

## Oracle Strength Assignment
OS class must follow `spec/oracle_strength_checklist.md`. Legacy letter grades are mapped to OS-1..OS-5 with explicit rationale and rater attribution.

## Baseline Methods
Baselines are specified in `case_studies/baselines/` and must use the same evidence packet, roots, and budget:
- checklist
- log-odds
- human expert

## Evaluator Validation (Prerequisite)
Evaluator consistency is required before running validation:
- Run 10 repeated evaluations on identical inputs.
- Target ICC >= 0.70 for p, ICC >= 0.60 for k.
- Document prompts and leakage checks.

## Phased Validation Plan
- Phase 0 (n=5-10): validate no-free-probability and calibration claims only.
- Phase 1 (n=20): add VOI-lite scheduling claim.
- Phase 2 (n=40+): full claims once evidence extraction reliability is proven.

## Artifacts Produced per Case
- `evidence_packet.md`
- `roots.yaml`
- `answer_key.md`
- `runs/` (ABDUCTIO and baselines)
- `results.json` (label-dependent + label-independent metrics)

## Limitations
- The reference outcome may be wrong or incomplete.
- Evidence packets are incomplete by design; confidence is expected to be bounded.
- Some cases may be open-world, and "undetermined" is a valid outcome.

## Intended Use
This validation is intended to show that ABDUCTIO behaves responsibly under limited evidence and strict budgets, and that its outputs are auditable, symmetric, and robust to representation artifacts.
