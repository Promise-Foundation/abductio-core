# Root Set Validation Protocol

## Purpose
Ensure MECE root sets are defensible and not gerrymandered.

## Requirements
1) Independent review by at least two domain experts.
2) Overlap scoring for each root pair (0-2 scale).
3) Completeness check: 90%+ of oracle conclusions must map cleanly.
4) Document any disagreements and resolution.

## Overlap scoring rubric
- 0: Mutually exclusive in scope.
- 1: Partial overlap or shared boundary cases.
- 2: Significant overlap; likely not MECE.

## Completeness check
- Map each oracle conclusion to the root set.
- Record ambiguous mappings and rationale.
- If ambiguity > 10%, revisit root granularity.
