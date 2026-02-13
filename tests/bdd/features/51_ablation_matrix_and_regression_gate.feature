# tests/bdd/features/51_ablation_matrix_and_regression_gate.feature
Feature: Ablation matrix and cross-domain non-regression gate
  # This feature enforces methodological evaluation of improvements across
  # frozen packets, fixed seeds, and held-out domains.

  # Benefit: we can attribute outcome changes to specific modules, not anecdotes.
  Scenario: Ablation matrix runs fixed variants against frozen baseline
    Given a frozen benchmark baseline named "boeing_safe_v1"
    And ablation variants are:
      | variant_id                 |
      | baseline_safe              |
      | plus_hunter_judge          |
      | plus_pair_value_priority   |
      | plus_dynamic_abstention_v2 |
      | plus_composition_reg       |
      | full_stack                 |
    And all variants use the same packet hash and seed set hash
    When I execute the ablation matrix
    Then the ablation report includes one row per variant
    And the ablation report records invariant fields:
      | field          |
      | baseline_id    |
      | packet_hash    |
      | seed_set_hash  |
      | model_id       |
    And the audit log records event "ABLATION_MATRIX_COMPLETED"

  # Benefit: outcome quality and epistemic quality are both tracked in one report.
  Scenario: Ablation report includes decisive and calibration metrics
    Given a completed ablation matrix result
    When I build the ablation summary
    Then each variant row includes metrics:
      | metric_name                  |
      | top1_selection_accuracy      |
      | top1_certification_accuracy  |
      | brier_mean                   |
      | calibration_ece              |
      | abstention_honesty_rate      |
      | credits_exhausted_rate       |
      | resolved_pair_coverage_mean  |

  # Benefit: global changes are blocked if any domain degrades beyond tolerance.
  Scenario: Cross-domain non-regression gate blocks release on held-out degradation
    Given held-out domain metric deltas versus baseline:
      | domain_id             | top1_selection_delta | brier_delta | calibration_ece_delta |
      | aviation_investigation| 0.04                 | -0.03       | -0.01                 |
      | macro_forecasting     | -0.08                | 0.06        | 0.03                  |
      | industrial_incident   | 0.01                 | -0.01       | 0.00                  |
    And non-regression tolerances are:
      | metric_name            | floor |
      | top1_selection_delta   | -0.03 |
      | brier_delta            | 0.02  |
      | calibration_ece_delta  | 0.02  |
    When I evaluate the non-regression release gate
    Then the release gate outcome is "FAIL"
    And the release gate report includes failing domain "macro_forecasting"
    And the audit log records event "CROSS_DOMAIN_NON_REGRESSION_FAILED"
