# tests/bdd/features/24_process_tracing_and_cross_domain_release_gates.feature
Feature: Process tracing and cross-domain release gates
  # This feature encodes the non-bandaid path to stronger zero-shot behavior:
  # add process-tracing constraints and evaluate on held-out domains.

  # Benefit: causal investigations cannot close confidently without a coherent
  # event-chain account (who did what, when, with what mechanism).
  Scenario: Causal profile requires process-tracing slot before confident closure
    Given default config:
      | tau        | 0.85 |
      | epsilon    | 0.05 |
      | gamma_noa  | 0.10 |
      | gamma_und  | 0.10 |
      | alpha      | 1.00 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key                | role |
      | availability            | NEC  |
      | fit_to_key_features     | NEC  |
      | defeater_resistance     | NEC  |
      | process_trace_integrity | NEC  |
    Given a hypothesis set with named roots:
      | id | statement                        | exclusion_clause                |
      | H1 | Procedural deviation explains it | Not explained by any other root |
      | H2 | Mechanical fault explains it     | Not explained by any other root |
    And domain profile "causal_investigation" is selected
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                | p    | A | B | C | D | evidence_ids |
      | H1:availability         | 0.85 | 2 | 2 | 2 | 2 | ref1         |
      | H1:fit_to_key_features  | 0.82 | 2 | 2 | 2 | 2 | ref2         |
      | H1:defeater_resistance  | 0.80 | 2 | 2 | 2 | 2 | ref3         |
      | H2:availability         | 0.40 | 2 | 2 | 2 | 2 | ref4         |
      | H2:fit_to_key_features  | 0.42 | 2 | 2 | 2 | 2 | ref5         |
      | H2:defeater_resistance  | 0.44 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the engine until it stops
    Then stop_reason is "EPISTEMICALLY_EXHAUSTED"
    And the audit log records event "PROCESS_TRACE_SLOT_REQUIRED"
    And the audit log records event "NEXT_STEPS_GENERATED"
    And next-step guidance includes slot "process_trace_integrity"

  # Benefit: release decisions are based on held-out domain behavior rather
  # than anecdotal single-case wins.
  Scenario: Cross-domain zero-shot release gate fails when held-out metrics are weak
    Given a held-out domain benchmark summary:
      | metric                        | value |
      | top1_accuracy_mean            | 0.41  |
      | top1_accuracy_min             | 0.20  |
      | brier_mean                    | 0.43  |
      | confidence_calibration_ece    | 0.18  |
      | run_to_run_top1_variance      | 0.29  |
      | abstention_honesty_rate       | 0.52  |
    And release gate thresholds:
      | metric                     | threshold |
      | top1_accuracy_mean         | 0.55      |
      | top1_accuracy_min          | 0.35      |
      | brier_mean                 | 0.30      |
      | confidence_calibration_ece | 0.10      |
      | run_to_run_top1_variance   | 0.15      |
      | abstention_honesty_rate    | 0.70      |
    When I evaluate the cross-domain release gate
    Then the release gate outcome is "FAIL"
    And the release gate report includes failing metrics:
      | metric                     |
      | top1_accuracy_mean         |
      | brier_mean                 |
      | confidence_calibration_ece |
      | run_to_run_top1_variance   |

  # Benefit: once thresholds are met, the release claim is explicit and scoped
  # to held-out domains rather than implied universal reliability.
  Scenario: Cross-domain zero-shot release gate passes when thresholds are met
    Given a held-out domain benchmark summary:
      | metric                        | value |
      | top1_accuracy_mean            | 0.63  |
      | top1_accuracy_min             | 0.44  |
      | brier_mean                    | 0.24  |
      | confidence_calibration_ece    | 0.07  |
      | run_to_run_top1_variance      | 0.10  |
      | abstention_honesty_rate       | 0.79  |
    And release gate thresholds:
      | metric                     | threshold |
      | top1_accuracy_mean         | 0.55      |
      | top1_accuracy_min          | 0.35      |
      | brier_mean                 | 0.30      |
      | confidence_calibration_ece | 0.10      |
      | run_to_run_top1_variance   | 0.15      |
      | abstention_honesty_rate    | 0.70      |
    When I evaluate the cross-domain release gate
    Then the release gate outcome is "PASS"
    And the release gate report records held-out domains count >= 3

