Based on the validation retrospective ("boeing_validation_methodology_retrospective_2026-02-12.md") and the surrounding context in the provided documents (including the white paper, BDD feature specs, and the AAIB accident report for the Boeing 737-8AS tail strike incident), I can outline a structured diagnosis of why ABDUCTIO-Core is failing to achieve robust outcome success on the Boeing case—specifically, why it doesn't recover the "oracle top root" (which, from the accident report, appears to be a hypothesis centered on ground handling procedural errors, instructor distraction during training, and contributing human factors like surprise, lack of team intervention, and inadequate visual cues like the TRP markings). I'll break this down into observed symptoms, root causes inferred from the system's design, and evidence from the docs. Note that the framework's emphasis on epistemic discipline and conservatism is a double-edged sword: it's mechanically sound but underpowered for "hard historical cases" like this one under constrained budgets.
Observed Symptoms of Failure (From the Retrospective)

Failure to Recover Oracle Top Root: Completed runs don't identify the ground handling error as the winner. Instead, mass concentrates on named roots that don't align with the true cause (e.g., perhaps overemphasizing mechanical or communication hypotheses without sufficient discrimination).
H_UND Dominance: Underdetermination residual (H_UND) absorbs most probability mass, indicating the system honestly admits insufficient evidence to adjudicate competitors confidently.
Credit Exhaustion Before Closure: Runs halt due to budget limits without meeting tau (confidence threshold, e.g., 0.70-0.90 across specs) or other stop conditions like frontier confidence.
Degraded Calibration in Variants: Some hardenings (e.g., composition in ablations) worsen metrics, suggesting instability when adding complexity.
Overall Assessment: Process validity improved (invariants hold, audits reproducible), but outcome success lags—coherent but "underpowered" on this case.

These align with the core objectives: the system prioritizes "epistemic discipline" (no inflation) and "auditability," but struggles with "comparative value" (measurable quality gains) in real-world scope.
Why Is ABDUCTIO Failing? Key Root Causes
ABDUCTIO's design is intentionally conservative and mechanistic to avoid common reasoning pitfalls (e.g., focal privilege, unjustified confidence), but this creates bottlenecks in hard cases like the Boeing incident, where evidence is multifaceted (human factors, procedures, visuals) and requires deep, contrastive adjudication. Here's a breakdown:

Excessive Conservatism and Underdetermination Bias (H_UND Dominance):
Core Issue: The framework enforces "no free probability" (feature 04) and explicit open-world residuals (H_UND/H_NOA, features 05, 01), defaulting unassessed nodes to neutral (p=0.5). This prevents inflation but amplifies uncertainty when evidence is sparse or non-discriminative. In the Boeing case, evidence like the trainee's hesitation or TRP obscurity might support multiple hypotheses (e.g., training error vs. marking inadequacy), leading to symmetric updates that don't shift mass decisively (feature 10: conservative deltas if no evidence_ids).
Evidence from Docs: The white paper and feature 32 (dynamic abstention mass) emphasize scaling H_UND with unresolved pair pressure. In strict modes (features 14-15, 23), incomplete contrastive adjudication blocks closure, reserving mass for H_UND if discriminators aren't fully covered (e.g., pairwise overlap bounds not met). The retrospective notes "H_UND still dominates," suggesting the system correctly detects underdetermination but doesn't resolve it—humans might intuitively favor the ground error hypothesis with the same evidence, but ABDUCTIO requires explicit, symmetric scrutiny (e.g., template parity in feature 02).
Why This Fails vs. Humans: Humans often use heuristics (e.g., Occam's razor) to break ties, but ABDUCTIO avoids this to maintain "permutation invariance" (feature 07) and "defeater resistance" (rubric in feature 09), leading to abstention.

Budget and Scheduling Constraints (Credits Exhausted Before Closure):
Core Issue: Operations (DECOMPOSE, EVALUATE, SEARCH) cost 1 credit each (feature 03), and scheduling is deterministic/round-robin (feature 06) to avoid focal injection. With finite credits, runs can't achieve sufficient depth—e.g., decomposing slots into children (feature 08: soft-AND coupling) or searching evidence (feature 13). The Boeing case likely requires VOI-lite scheduling (lambda_voi=0.10) to prioritize high-value nodes, but if frontier selection ties (e.g., multiple UNSCOPED roots), credits spread thin without closure (tau not met).
Evidence from Docs: Retrospective highlights "credits are exhausted before closure requirements are met." Features like 34 (budget-feasible pairs) and 39 (counterevidence reservation) add partitions, reserving credits for adversarial checks—but if the active set grows (features 27, 36), it caps scope, preventing full adjudication. In hardenings (features 17-20), caps like forecasting hard cap (0.55) or dependency penalties (feature 19) further limit confidence, exhausting runs on invariants without outcome progress.
Why This Fails vs. Humans: Humans adaptively focus (e.g., prioritize tug instructor statements), but ABDUCTIO's "VOI-lite" and pair queues (features 31, 35) are non-adaptive to interim scores, ensuring fairness but slowing resolution.

Incomplete Frame and Hypothesis Adequacy:
Core Issue: The system requires a MECE hypothesis set (features 01, 14: strict certification with pairwise discriminators), but if the initial frame misses nuances (e.g., "startle/surprise" from the report), scoping fails (feature 02: UNSCOPED caps k<=0.40). Domain induction (feature 22) might misbind policies (e.g., "forecasting" vs. "causal" profile needing process-tracing in feature 24), leading to weak frames that cap confidence (feature 17: frame adequacy score=0.30 reserves abstention).
Evidence from Docs: Retrospective mentions "frame adequacy" hardenings and "internally coherent but underpowered." In the white paper's Ariel School example (J.4), anomalous H3 wins modestly (p=0.52, k=0.65) with residuals—similar to Boeing, where evidence underdetermines without deep tracing (e.g., no "compositional stories" expansion in feature 33 to combine training + markings).
Why This Fails vs. Humans: Humans dynamically refine frames; ABDUCTIO's contender semantics (feature 28) are static unless auto-expanded, and contrastive gates (features 23, 25-26, 29) block if discriminators lack quotes/typing (feature 37).

Evidence Search and Integration Gaps:
Core Issue: Replayable search (feature 13) is symmetric and quota-limited, but might not fetch discriminative evidence (e.g., CCTV footage or instructor statements). Evaluator contracts (feature 10) constrain updates without evidence_ids, and hardenings require typed discriminators (features 29, 38) with quote fidelity (feature 37), degrading if mismatched.
Evidence from Docs: Partial runs show "directional improvement in mass allocation" with mechanisms active, but live track caught "inference wiring bugs in pair-target propagation" (feature 40). If search quotas are per-slot symmetric, Boeing's multi-factor cause (distraction + no intervention) might not discriminate enough.
Why This Fails vs. Humans: Humans integrate holistically; ABDUCTIO's auditability (feature 11) demands explicit ties, leading to conservative deltas.

Calibration and Hardening Trade-offs:
Core Issue: Variants degrade due to added complexity (e.g., parent k propagation in feature 12 caps if any rubric=0). Cross-domain gates (feature 24) might flag "unvalidated" calibration, capping k<=0.55 (feature 17).
Evidence from Docs: Retrospective notes degraded calibration in ablations; hardenings like dependency penalties (feature 19) or churn accounting (feature 36) add realism but increase H_UND.
Why This Fails vs. Humans: Humans tolerate overconfidence; ABDUCTIO enforces "defeater resistance" and guardrails.


Recommendations to Improve
To close the gap with human reasoners (who balance boldness with evidence), focus on targeted relaxations while preserving validity:

Increase Budget/Depth: Triple credits in validations to allow deeper decomposition (e.g., process-tracing slots in causal profiles).
Enhance Evidence Handling: Boost search quotas and integrate quote-tolerant fidelity (feature 37) to reduce degradation.
Refine Framing: Use domain profiles (feature 22) with auto-expansion for compositional stories (feature 33) to better capture multi-factor causes.
Mode Flexibility: Run in "explore" mode (feature 20) to relax strict gates, then certify.
Benchmark Tweaks: Add human-like heuristics (e.g., mild Occam prior) in variants, but audit impacts.
Next Validation Step: As suggested, run hardened T0-T3 with matched evidence—focus on pair queues (feature 31) for Boeing's human factors.

