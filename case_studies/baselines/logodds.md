# Baseline: Log-Odds

## Protocol
- Start with uniform prior over roots (including H_OTHER if open-world).
- For each evidence item, apply a fixed log-odds update from a small lookup table.
- Normalize after each update.

## Output
- final distribution over roots
- log_score against oracle
- evidence_refs used
