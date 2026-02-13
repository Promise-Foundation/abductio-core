# Mapping Notes: Grok Expert -> Canonical Interface

## Source
- Raw response file: `/Users/davidjoseph/github/abductio-core/case_studies/data/UK_AAIB_Reports/results/comparisons/Boeing_737-8AS_9H-QAA_12-25/20260212T052107Z_grok_expert/raw_response.txt`
- Shared link: [https://grok.com/share/c2hhcmQtMw_75280523-061e-4a46-96f0-8af66bc90ba0](https://grok.com/share/c2hhcmQtMw_75280523-061e-4a46-96f0-8af66bc90ba0)

## Transform decisions
1. Kept rank ordering exactly as provided.
2. Preserved original credence values as `raw_credence_percent`.
3. Normalized credences proportionally because source sum was 230%, not 100%.
4. Mapped confidence labels to numeric values for comparability:
   - `High` -> `0.85`
   - `Medium` -> `0.65`
5. Root mapping used current Boeing singleton root taxonomy when direct:
   - C1 -> `R1_PUSHBACK_PROCEDURAL_DEVIATION`
   - C2 -> `R2_COMMUNICATION_BREAKDOWN`
   - C3 -> `R3_ENVIRONMENT_OR_MARKING_DEFICIENCY`
6. C4/C5 were left `mapped_root_id = null` because they do not cleanly map to a single existing root in the current set.

## Caution
This transformed file is for comparison convenience, not ground truth.
The strongest comparison remains:
- same evidence packet,
- same root set,
- same budget,
- same output contract,
- same scoring script.
