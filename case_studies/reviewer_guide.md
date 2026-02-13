# ABDUCTIO Case Studies - Reviewer Guide

This document is for first-time reviewers. It explains what the case studies are meant to demonstrate, the philosophy behind them, and how to create or review case studies. It includes verified commands you can run locally.

## 1) What the case studies are meant to demonstrate

ABDUCTIO case studies are benchmarks for *responsible inference under limited evidence*. They are designed to show:

- Auditability: every belief update is traceable to evidence and logged operations.
- Humility under uncertainty: confidence remains bounded when evidence is thin.
- Robustness: results are stable across ordering and representation choices.
- Fairness: identical inputs, scopes, and credit budgets across methods.
- Agreement-with-oracle as a reference (not Truth): scores are interpreted as agreement with a later, better-resourced inference state.

These studies are not claims of ground truth. They are evidence that ABDUCTIO behaves responsibly when the correct answer is not fully knowable at evaluation time.

## 2) Philosophy and validation posture

- Oracles are fallible. Agency conclusions are treated as later inference states, not Truth.
- Evidence is frozen at time T. Only what was knowable at time T is allowed.
- No-hindsight leakage is enforced. Causal or interpretive statements are held out.
- MECE root sets are required. Hypotheses are mutually exclusive and collectively exhaustive for the scoped question.
- Fairness is mandatory. Same scope, evidence, roots, and budget across methods.

Canonical validation strategy and rules:
- `case_studies/unified_empirical_strategy.md`
- `case_studies/abductio_v2_validation_framework.md`

## 3) How to create a new case study

These steps use the AAIB tooling in this repo. Replace `<case_id>` and filenames as needed.

### 3.1 Select a case and define scope
- Choose a single question (S1 proximate cause or S2 preventable cause).
- Define the unit of analysis (problem-level preferred).
- Define evidence freeze time T.

### 3.2 Add the case to the registry (public-web download workflow)

1) Add or update the case row in `case_studies/data/UK_AAIB_Reports/index.csv` with:
- `case_id`
- `source_url` (for AAIB, usually `https://www.gov.uk/aaib-reports`)
- `source_doc_id` (for example `AAIB-30304`)
- `doc_title`
- `pdf_filename` (target local filename)

2) Download the source PDF programmatically from public web sources:

```
python -m case_studies.tools.aaib_bench.aaib_bench download --case <case_id>
```

3) Optional bulk mode:

```
python -m case_studies.tools.aaib_bench.aaib_bench download --selected
```

4) Manual fallback (if the resolver fails for a specific case):
- Place PDF in `case_studies/data/UK_AAIB_Reports/`
- Keep `pdf_filename` in `index.csv` aligned with the local file

### 3.3 Prepare extracted sections (required by the build tool)

The build tool requires extracted sections to exist in:

```
case_studies/data/UK_AAIB_Reports/extracts/<case_id>/
```

Required files:

```
history.txt
synopsis.txt
analysis.txt
conclusion.txt
safety_actions.txt
```

If these files are missing, the build will fail. The extraction step is currently manual or external to this repo.

### 3.4 Build the evidence packet (E_T)
- Include only factual header fields and factual narrative.
- Exclude analysis, conclusion, and safety actions.
- Remove causal phrasing and hindsight framing.
- Record provenance and hashes.

### 3.5 Define the MECE root set
- Create roots with explicit exclusion clauses.
- Include H_other or H_undetermined if open-world.
- Validate with the root set validation protocol.

### 3.6 Create the oracle and answer key
- Extract the reference statement from conclusion/analysis/synopsis causal lines.
- Map the reference to a root ID.
- Assign oracle strength (OS class) with rationale.

### 3.7 Build and validate the case artifacts

Build the case artifacts:

```
python -m case_studies.tools.aaib_bench.aaib_bench build --case <case_id>
```

Validate the case artifacts:

```
python -m case_studies.tools.aaib_bench.aaib_bench validate --case <case_id>
```

End-to-end pipeline (download + build + validate, plus optional run):

```
python -m case_studies.tools.aaib_bench.aaib_bench pipeline --case <case_id>
python -m case_studies.tools.aaib_bench.aaib_bench pipeline --selected --run
```

Pipeline writes a JSON and CSV report to:
`case_studies/data/UK_AAIB_Reports/results/pipeline/`

### 3.8 Generate run artifacts
- Run ABDUCTIO and baselines under identical scope and budget.
- Capture p/k traces, credit ledger, and allocation traces.
- Produce results.json with label-dependent and label-independent metrics.

### 3.9 Required per-case outputs
- `evidence_packet.md`
- `roots.yaml`
- `answer_key.md`
- `oracle.md` (or structured equivalent)
- `runs/` with logs
- `results.json`
- `hashes.txt` or build manifest with inputs/outputs

For AAIB cases, also follow:
- `case_studies/data/UK_AAIB_Reports/methodology.org`
- `case_studies/data/UK_AAIB_Reports/spec/evidence_packet_protocol.md`
- `case_studies/data/UK_AAIB_Reports/spec/leakage_checks.md`

## 4) How to review existing case studies

### 4.1 Check the evidence packet for leakage
- Confirm only factual sections are used.
- Scan for causal language (e.g., "caused", "resulted from", "therefore").

Quick scan command:

```
rg -n "cause|caused|resulted from|therefore|led to" case_studies/data/UK_AAIB_Reports/cases/<case_id>/evidence_packet.md
```

Validate evidence JSON and root mappings:

```
python -m case_studies.tools.aaib_bench.aaib_bench validate --case <case_id>
```

### 4.2 Validate root sets
- Ensure roots are MECE with exclusion clauses.
- Confirm open-world handling if the oracle is undetermined.
- Check that roots align with the stated scope.

### 4.3 Verify oracle mapping and strength
- Confirm the reference statement exists and is sourced.
- Check that the oracle maps to a valid root ID.
- Ensure OS class and rationale are provided.

### 4.4 Review run artifacts and metrics
- Verify logs are complete and reproducible.
- Confirm no-free-probability invariants.
- Check label-dependent metrics are reported with OS context.
- Review label-independent metrics for auditability and robustness.

### 4.5 Evaluate disagreement handling
- If ABDUCTIO diverges from the oracle, confirm D0-D4 classification.
- Ensure justified dissent criteria are documented with evidence refs.

## 5) Example commands (run in this repo)

The following commands are the standard workflow commands for this repo:

```
python -m case_studies.tools.aaib_bench.aaib_bench --help
python -m case_studies.tools.aaib_bench.aaib_bench download --case Boeing_737-8AS_9H-QAA_12-25
python -m case_studies.tools.aaib_bench.aaib_bench build --case Boeing_737-8AS_9H-QAA_12-25
python -m case_studies.tools.aaib_bench.aaib_bench validate --case Boeing_737-8AS_9H-QAA_12-25
python -m case_studies.tools.aaib_bench.aaib_bench pipeline --case Boeing_737-8AS_9H-QAA_12-25
rg -n "cause|caused|resulted from|therefore|led to" case_studies/data/UK_AAIB_Reports/cases/Boeing_737-8AS_9H-QAA_12-25/evidence_packet.md
```

## 6) Minimal reviewer checklist (quick pass)

- Evidence packet contains no analysis/conclusion/safety actions.
- MECE roots include exclusions and H_other if needed.
- Oracle mapping is explicit with OS class and rationale.
- Runs have logs, traces, and results.json.
- Metrics include both agreement and responsibility.
- Disagreements are classified and justified.
