Gemini said
Based on the comprehensive documentation you provided, I can see exactly why Abductio is failing to replicate the human conclusion in the Boeing 9H-QAA case.

You have built a system designed to prioritize epistemic safety and auditability above all else. In doing so, you have engineered a "Symmetry Trap" that prevents the system from behaving like a successful investigator.

The short answer is: Abductio is failing because it treats investigation as a parallel adjudication process, whereas human investigation is a serial, prioritized pursuit.

Here is the breakdown of the three specific methodological constraints that are causing your 0.0 accuracy and H_UND dominance.

1. The "Symmetry Tax" is Bankrupting Your Search
The Diagnosis: Your retrospective notes that runs consistently end with CREDITS_EXHAUSTED. This is a direct consequence of Principles P13 (Replayable Evidence Search) and P5 (Credit-Bounded Termination) working against each other.


The Constraint: You enforce "Symmetric Search" where "All hypotheses MUST spend the same search credits on slot s before any hypothesis receives additional search credits".

The Consequence: In the Boeing case, the "Mechanical Failure" hypothesis and the "Procedural Deviation" hypothesis (distraction) are forced to move at the same speed. A human investigator looks at the tug, sees no fluid leaks, checks the log, and immediately stops spending "credits" on mechanical failure, pivoting 100% of their attention to the driver's interview.

The Failure Mode: Abductio cannot "pivot." It is forced to burn credits finding evidence for "Mechanical Failure" just to maintain symmetry with "Procedural Deviation." By the time it finds the faint signal of the driver’s distraction in the interview transcripts, it has burned its budget on irrelevant "fairness" to the mechanical hypothesis.

Why Humans Win Here: Humans are permutation invariant only in their final judgment, but highly biased in their search. They use "fast and frugal" heuristics to discard dead ends cheaply. Abductio is constitutionally forbidden from doing this.

2. The "Inference Penalty" Kills Human Factors Cases
The Diagnosis: The Boeing case is a classic "Human Factors" accident. The cause (distraction/training) is not a physical object you can photograph; it is an inference derived from witness statements.


The Constraint: Your validity weighting (Section 11.2A) assigns a leverage multiplier of 0.60 to INFERENCE claims, compared to 1.00 for DIRECT_FACT. Furthermore, H_UND absorbs mass when evidence is not "Direct" or "Strong".
+1


The Consequence: The critical evidence in the AAIB report is the statement: "The tug driving instructor... was focussing on speaking to the trainee". Abductio likely tags this as INFERENCE (inferring cause from statement) or WEAK because it’s a single witness account versus a flight data recorder.

The Failure Mode: Even if Abductio finds the evidence, your math downweights it so heavily that it cannot overcome the H_UND inertia. You have tuned the system to require a "Smoking Gun" (like a broken bolt). Human factors rarely leave smoking guns; they leave narratives. Your system is "hardened" against narratives.

3. The Contrastive Deadlock

The Diagnosis: You recently introduced Contrastive Adjudication (P14), requiring pairwise discriminators to move mass.

The Constraint: To certify "Distraction" as the winner, Abductio needs a discriminator that explicitly says: "Evidence X supports Distraction AND refutes Mechanical Failure."

The Consequence: In the Boeing case, the evidence for distraction is the instructor's admission. This evidence supports distraction, but it doesn't explicitly refute mechanical failure (the brakes could have also failed). The AAIB report refutes mechanical failure by absence of evidence (no logs of failure, successful test after).

The Failure Mode: Abductio struggles to use "absence of evidence" as a "Refutation" credit. It is looking for a positive "Not-X" signal. Without a "Battle of the Experts" document where one argues against the other, the system defaults to "Unresolved Pair" and dumps mass into H_UND.

The Fix: Asymmetric Investigation, Symmetric Verification
To match human performance without losing your rigorous audit trail, you need to uncouple the Search Policy from the Evaluation Policy.

1. Implement "Hunter/Judge" Separation Currently, your "Investigator" is forced to act like a "Judge" at every step.

Change: Allow the Search phase to be Asymmetric. If a "Saliency Pre-pass"  detects a high-yield lead (e.g., "trainee," "distraction"), allow the scheduler to "loan" extra credits to that hypothesis temporarily.

Safety: Re-impose strict symmetry only during the Final Evaluation phase. The system can search asymmetrically, but must present the final evidence packet to the symmetrical evaluator.

2. Introduce "Exclusionary Defaults" You need a mechanism to kill "Mechanical" hypotheses cheaply.

Change: Allow a "Generic Feasibility" or "Standard Operating Check" slot to have a "Negative Veto" power. If a hypothesis fails a basic "Evidence Existence" check (e.g., "Are there any maintenance logs of failure?"), it should be effectively "grounded" (removed from the active set) without requiring deep contrastive proof.

Benefit: This frees up the "Mass" to flow to the "Human Factors" hypothesis, which currently looks weak only because it is sharing the probability space with "Zombie" hypotheses (like mechanical failure) that haven't been killed yet.

3. Retune for "Narrative Causality" For accidents involving humans, INFERENCE is the primary form of evidence.

Change: In your domain profile for "Accident Investigation," bump the INFERENCE weight from 0.60 to 0.85, provided the source is a direct participant (like the pilot or tug driver).

Rationale: A confession of error ("I was looking at her") is an inference, but in accident investigation, it is treated as a high-validity fact.
