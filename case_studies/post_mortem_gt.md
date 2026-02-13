1) You have engineered a “high bar to commit” system, then measured it with a “must commit” scoreboard

Your stated objective emphasizes epistemic discipline (“no unjustified confidence inflation; explicit handling of underdetermination”) and tougher closure semantics for decision safety (multiple hardening features), and your observed outcomes are exactly what one should expect under that regime: high abstention and frequent CREDITS_EXHAUSTED before closure criteria are met.

But then the headline dissatisfaction is “top-1 accuracy remains 0.0” and “Top root frequently = H_UND.”
That is a mismatch: a system optimized to avoid overcommitment will often “lose” top-1 against a human who is willing to name the most plausible story even when several alternatives remain live.

Concretely: top-1 is a brittle metric when abstention is an admissible (and encouraged) output. Your own results show partial improvements in Brier (calibration proxy) from pair-adjudication variants without any top-1 recovery.
That is exactly the signature of “safer but less decisive.”

2) The closure requirements + pairwise adjudication are budget-infeasible for the size/geometry of the hypothesis set

You explicitly note: fixed credit budget (often 150), runs end with CREDITS_EXHAUSTED, and closure criteria remain unsatisfied.

Once you require active-set adjudication completeness (and related gates), the work required scales roughly like the number of “meaningfully competing” pairs, not like the number of roots. Even if you prune, any churn/retargeting creates additional overhead (you added churn accounting precisely because this happens).

So, mechanically, what happens is:

the engine starts doing the “right” thing (queue active; you saw ~10–11 PAIR_ADJUDICATION_TARGET_SELECTED per stage),

but the budget is too small to finish the adjudication program,

therefore the safety logic is forced to park a lot of mass in abstention,

and you terminate on credits, not on epistemic resolution.

This is not primarily an LLM “reasoning” failure; it is a computational feasibility failure induced by the validation contract.

3) The “oracle root” is actually a composite causal story in the AAIB report, but you are scoring it as a singleton winner

Look at what the AAIB report is doing. The “procedural deviation” (pushed beyond the TRP) is the proximal event, but the report’s causal texture is explicitly multi-factor:

tug instructor attention captured by training / communication while driving, leading to passing the TRP

TRP salience/visibility issues (“not very prominent”, “obscured”), plus “no thrust opposing idle engine power” affecting expectation of stopping

wingman/headset operator did not challenge because they assumed the instructor had a reason; delayed intervention; surprise/startle dynamics

Humans will still name a single “main cause” when asked, but cognitively they are comfortable compressing a multi-cause narrative into one label. Your system, by design, penalizes that compression unless the contrastive evidence cleanly knocks down the other live contenders. That pushes you toward H_UND unless you either:

allow/privilege a compositional “story root” (and score against that), or

introduce an explicit main-cause selection rule (a lossy projection) that humans implicitly apply.

Your ablation result that “composition worsened Brier” in one run does not imply composition is wrong; it may mean your current composition mechanism is not well-regularized/calibrated yet, or that it is being asked to do too much under too little budget.

4) Evidence-to-hypothesis typing is likely starving the discriminators of “obvious” linkages

From the report, there are very “typed” discriminative hooks: TRP exists; there is a TRP marking; tug should stop; it didn’t; collision followed.
A human immediately maps that to “pushback procedural deviation / failure to stop at TRP.”

If ABUCTIO still cannot concentrate probability on R1_PUSHBACK_PROCEDURAL_DEVIATION, that strongly suggests that, somewhere in the pipeline, the evidence is not being represented in a way that lets the contrastive evaluator treat it as decisive against specific alternatives—so it stays “generally consistent with many stories,” which your contrastive conformance rules treat as non-discriminative drift.

Your own retrospective shows that when the queue and binding bugs are fixed, H_UND mass drops (≈0.47 → ≈0.20–0.23) and oracle mass rises (≈0.09–0.12 → ≈0.14–0.19), but you still run out of credits.
That is exactly what you would see if: the discriminators work when pointed at the right pairs, but too few decisive discriminations are completed before budget exhaustion.

5) “Underdetermination dominates” may be correct under your contract, but incorrect under the human contract you are implicitly benchmarking against

Your conclusion line is telling: “internally coherent but still underpowered … under current budget/evidence regime.”
I would sharpen that: under your present rules, even a human constrained to (a) the same strict closure gates and (b) the same pairwise completeness requirement and (c) the same credit budget, would also frequently fail to “certify” a winner. Humans “win” because they do not actually run that contract—they terminate early with a best explanation.

So ABUCTIO is not merely “failing to reason like a human”; it is reasoning under a stricter epistemic calculus than the human comparator, then being graded as if it had used the human calculus.

What I would change (high leverage)

Separate “selection” from “certification” in scoring.
Keep your certification gate for safety, but score two outputs:

best current explanation (allowed to be provisional), and

certified explanation (may abstain).
Right now you are forcing one object to satisfy both.

Make budget feasibility an explicit precondition of the contract.
If closure requires adjudicating 
𝑚
m unresolved discriminations, then either increase budget adaptively or relax completeness to a stopping rule that is provably “good enough” (e.g., stop when additional adjudication cannot change the top-1 beyond ε).

Score and/or privilege compositional roots for cases whose ground truth is multi-factor.
The AAIB narrative is multi-causal even though it contains a clear proximal deviation.
If your ontology forces a singleton “winner,” you are demanding a lossy compression that your epistemic discipline is (correctly) reluctant to perform.

Audit the evidence typing around TRP and “procedural deviation.”
In this case, typed evidence should make it cheap to discriminate “failed to stop at TRP” from many other roots. If the system cannot do that quickly, the bottleneck is likely representational (what gets extracted/typed) rather than inferential.

If you want, I can be more concrete by taking just the AAIB text you provided and sketching what the minimal discriminative evidence graph should look like (what claims/types must exist so that R1_PUSHBACK_PROCEDURAL_DEVIATION dominates quickly), and where H_UND is mathematically forced to remain high given your current closure gates and budget.

would you say the abductio methodology is flawed?

I would not call the methodology “flawed” in the sense of being irrational or unusable—but it is misaligned with the claim you want to validate (“at least as good as human reasoners, given the same evidence”), and that misalignment is strong enough that it will systematically make Abductio look worse than humans on your headline metrics.

Here is the core issue:

The methodology conflates two different tasks
Task A: Epistemically safe certification

“Only commit when the hypothesis is sufficiently separated from alternatives under stringent closure constraints.”

Task B: Human-like selection under uncertainty

“Name the best explanation given limited time/budget, even if alternatives remain live.”

Your current protocol heavily rewards Task A behavior (abstain unless closure), and then scores primarily as if you were trying to optimize Task B (top-1 accuracy / winner selection). Under that pairing, abstention and H_UND are not bugs; they are the expected optimum.

So the methodology isn’t “wrong,” but it forces a system optimized for calibration/abstention to compete on decisiveness, which humans obtain by using a different stopping rule.

A second structural problem: the protocol can be budget-infeasible

With pairwise adjudication, active-set churn handling, and closure gates, the amount of work required can easily scale beyond a fixed credit budget. When that happens, outcomes are dominated by CREDITS_EXHAUSTED, and the reported failure becomes partly “the test harness did not allow enough computation to finish its own required steps,” rather than “the reasoner is inferior.”

A third problem: ground truth is often multi-factor, but scoring is singleton

In your Boeing case, the official narrative is multi-causal even if it highlights a proximal procedural deviation. If you score only a single root as correct, you are implicitly applying a human compression heuristic (“main cause”) that Abductio is explicitly designed to resist unless warranted.

What I would conclude

Not flawed as a research methodology for epistemic safety/certification.

Flawed (or at least incomplete) as a methodology for demonstrating “human parity” in the everyday sense, because it does not evaluate the same decision rule humans are using.

Minimal fix that would make the evaluation fair

Report two outputs and two scores:

Best-current hypothesis (selection): “If forced to pick now, what’s top-1 and its probability?”

Certified hypothesis (abstention allowed): “Do you meet closure? If not, abstain.”

Humans can be evaluated the same way (forced-choice + confidence and optional abstention under a stated certification bar). Then you can say whether Abductio is worse at selection, better at calibration, or simply stricter.

If you adopt that split, you will likely find that Abductio is not “failing to reason,” but rather behaving consistently with its epistemic contract—and being graded under a different contract.

but isn't this already implicit in the system?  even if the system can't certify something it still ranks the best explanations - and it is failing to actually come up with the best explanation
Thought for 13s

You are correct that, in principle, Abductio already “ranks” even when it cannot certify. Your Boeing traces show exactly that: it produces a distribution and a top root at each stage.

However, what your results indicate is that the ranking you are reading as “best explanation” is not actually a pure best-explanation ranking over substantive causal roots. It is a ranking in a contender space in which H_UND is itself a first-class contender whose score is structurally advantaged under your current contracts and budget regime. That is why you see “best explanation” = H_UND, even when the evidence (by human standards) strongly favors procedural deviation.

1) “Best explanation” is currently “best contender,” and H_UND is a contender with an easier win condition

In your completed non-hardened run, the top root is H_UND at all stages with mean top-root probability ≈ 0.47–0.49, while the oracle root mass is ≈ 0.09–0.12.
That pattern is difficult to reconcile with “the system is trying its hardest to pick a substantive best explanation,” because the AAIB report contains several direct statements that the tug continued beyond the TRP where it “was meant to stop,” then hit the barrier. The report’s conclusion reiterates that the aircraft was pushed beyond the TRP while the instructor was focused on training.

So the question becomes: why does H_UND outscore a root that is explicitly supported by the evidence?

Because in your framework as described in the retrospective, the scoring/updates are designed so that unresolved discrimination work and incomplete adjudication preserve large abstention mass, and credit exhaustion frequently occurs before that mass can be safely reallocated. In other words: ranking exists, but it is dominated by a deliberately conservative “unknown” contender whenever the system cannot complete its discrimination program under budget.

2) The ranking is not “what hypothesis best explains the evidence?”; it is “what contender can justifiably earn probability mass under the current conformance/typing gates?”

This is the key methodological subtlety.

Even if the correct root is plainly supported in natural language, it will not gain decisive mass unless the evidence is (a) extracted/typed in the right discriminator schema and (b) successfully applied in contrastive pair adjudications against the right rivals. Your own debugging history shows this can fail mechanically (pair-target misbinding) and that fixing it improved allocation directionally (lower H_UND, higher oracle mass) without yielding winner recovery.

That is strong evidence that your remaining issue is not “no ranking,” but insufficient throughput of decisive discriminations, either because:

the typed discriminators are not being produced for the most decisive facts (“tug meant to stop at TRP but did not”), or

the pair queue spends credits on many low-value comparisons before it finishes the few comparisons that would collapse the contender set, or

the update rule penalizes “non-discriminative drift” so aggressively that even highly relevant but not perfectly typed evidence does not move mass.

3) Your evidence is decisive, but your hypothesis ontology may be mismatched to how the report actually attributes causality

The AAIB account is multi-factor: training distraction, TRP salience, lack of challenge by wingman/headset operator, expectation effects from engines not started, etc.
If your contender set contains several plausible “nearby” roots (eg, “human factors—distraction,” “markings inadequate,” “team failed to intervene,” etc.), then a system that requires contrastive separation to move mass may treat these as mutually supporting rather than cleanly exclusive. In that geometry, no singleton root becomes a dominant peak, and H_UND remains the safest “winner.”

That would look, externally, like “it can’t even pick the best explanation,” but internally it is “the ontology made ‘best’ ill-posed without a main-cause projection.”

4) A concrete diagnostic: are you evaluating “best substantive root” or “best contender including abstention”?

Right now, your headline “top-1 accuracy” is being recorded with top_root_id = H_UND.
That obscures a crucial distinction:

Rank among substantive roots (excluding H_UND) might already place R1_PUSHBACK_PROCEDURAL_DEVIATION near the top.

But if H_UND is allowed to compete, it can win simply because you have made it cheap to justify compared to any specific causal root under incomplete adjudication.

This is not a rhetorical point: it changes what it means to say “it failed to come up with the best explanation.”

The methodological bottom line

If by “best explanation” you mean “the single most plausible causal story a human would name after reading the packet,” then yes: your current methodology is set up so that H_UND can dominate that ranking whenever (i) decisive evidence is not strongly typed into your discriminator interface and/or (ii) the budget ends before the contrastive program finishes.

This is why you can have (a) explicit textual support for the oracle root in the AAIB report and yet (b) persistent top-1 = H_UND in completed runs.

What would most directly answer your question (“is it failing to pick the best explanation?”)

Two checks that will settle it empirically:

Compute “best non-H_UND root” accuracy (and its probability) at each stage, alongside the current “best contender” metric.
If Abductio is actually ranking the oracle root highest among substantive roots, your failure is primarily “abstention dominates.” If it is not, the failure is “it cannot extract/apply the decisive discriminators.”

Instrument whether the decisive facts are ever typed into the contrastive interface:
e.g., a typed claim equivalent to “TRP reached; tug was meant to stop; continued beyond; collision followed.” The AAIB text states this directly.
If that typed claim is missing or treated as non-discriminative, the ranking failure is downstream of evidence typing, not “reasoning” in the abstract.

If you paste (or point me to) one representative stage trace showing: (i) the extracted typed evidence items and (ii) the top 5 substantive roots with their scores, I can tell you which side you are on—“abstention swamping” versus “substantive misranking”—and which mechanism is the primary culprit.
