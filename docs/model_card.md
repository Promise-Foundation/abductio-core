# ABDUCTIO Engine Model Card (v2)

## Purpose
ABDUCTIO ranks competing hypotheses under an explicit evidence budget. It is designed for auditable, conservative inference rather than truth claims.

## Core semantics
- `p(node)` is the model's probability that a node statement holds given the evidence packet provided for the session.
- `k(node)` is a reliability score for that evaluation, derived from a rubric and capped by evidence quality and assumptions.

## Update rule (ledger)
Let `p(H)` be the current ledger mass for hypothesis `H`.

For each required slot `s` on `H`, we compute a weight:
```
w_s = clip(beta * k_s * logit(p_s), -W, +W)
```

We apply a delta update in log space and renormalize:
```
log p'(H) = log p(H) + sum_s (w_s - w_s_prev)
```

`beta` scales evidence impact, `W` caps adversarial or noisy deltas, and logit keeps updates in odds space rather than raw probabilities.

Optional damping blends the prior and updated ledger:
```
p_damped = alpha * p_prev + (1 - alpha) * p_new
```

## Coupling
Slot decomposition supports:
- AND: soft AND with coupling `c` blending `min(p_children)` and `prod(p_children)`.
- OR: soft OR using `max(p_children)`.

AND is default; OR should be used only when the decomposition is explicitly disjunctive.

## Open-world absorber
When `world_mode = open`, an `H_other` absorber carries residual mass so that uncertainty is explicit. Closed-world mode removes `H_other` and normalizes named roots only.

## Reliability mapping (k)
`k` is a policy mapping from rubric scores (A-D) and evidence quality:
- Higher rubric totals yield higher base `k`.
- Guardrails cap `k` if any rubric element is 0.
- Missing evidence IDs, weak/indirect evidence, quote mismatches, or explicit assumptions cap `k`.

This mapping is a documented policy and should be calibrated on labeled data where possible. Until calibrated, sensitivity analysis should be reported when `k` materially affects conclusions.

## Evidence constraints
Evaluations must cite evidence item IDs from the evidence packet. Any assumptions must be explicitly listed and trigger reliability caps. Quotes, when provided, are validated against evidence spans.

## Stopping policy
Stopping reasons are decision policies (budget exhausted, frontier confident, no legal op), not claims of truth.

