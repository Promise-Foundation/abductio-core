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

## Serialization contract (benchmark runner)
Store validated certificates in `spec/roots_library.json` (and keep YAML in sync) under each `root_set`:

- `strict_mece_default: true` to enforce strict mode for benchmark runs.
- `max_pair_overlap: <float>` threshold.
- `mece_certificate.max_pair_overlap: <float>` (same threshold).
- `mece_certificate.pairwise_overlaps`: one entry for every unordered named-root pair (`ROOT_A|ROOT_B` -> score 0..2).
- `mece_certificate.pairwise_discriminators`: one non-empty discriminator text per unordered named-root pair.
