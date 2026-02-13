# External LLM Comparison Results

This folder stores non-ABDUCTIO outputs converted into the same result interface for side-by-side scoring.

## Structure
- `<case_id>/<timestamp>_<system>/raw_response.txt`
- `<case_id>/<timestamp>_<system>/canonical_result.json`
- `<case_id>/<timestamp>_<system>/mapping_notes.md`

## Rules
1. Always store raw source output verbatim.
2. Record any normalization or mapping assumptions explicitly.
3. Do not overwrite prior runs; append with new timestamped folders.
4. Keep evidence packet and case id explicit in each artifact.
