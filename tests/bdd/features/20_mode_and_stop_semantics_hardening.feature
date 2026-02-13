# tests/bdd/features/20_mode_and_stop_semantics_hardening.feature
Feature: Mode and stop semantics hardening
  # This feature separates exploratory reasoning from certification and makes
  # stop reasons epistemically explicit.

  # Benefit: prevents running a configuration that cannot possibly satisfy the
  # closure threshold (cap < tau) while still pretending certification succeeded.
  Scenario: Certify mode rejects policy-threshold conflicts before spending credits
    Given default config:
      | tau        | 0.75 |
      | epsilon    | 0.05 |
      | gamma_noa  | 0.10 |
      | gamma_und  | 0.10 |
      | alpha      | 1.00 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And reasoning mode is "certify"
    And reasoning profile is "forecasting"
    And historical calibration status is "unvalidated"
    And forecasting confidence hard cap is 0.55
    And credits 12
    When I run the simplified claim interface until it stops
    Then stop_reason is "POLICY_CONFIG_INCOMPATIBLE"
    And no operations were executed
    And the audit log records event "POLICY_CONFLICT_DETECTED"
    And audit event "POLICY_CONFLICT_DETECTED" payload includes:
      | field      |
      | tau_config |
      | k_cap      |
      | mode       |

  # Benefit: exploratory mode stays useful for humans by adapting closure target
  # to what policy allows, instead of dead-ending with an impossible threshold.
  Scenario: Explore mode adapts closure target when confidence cap is below tau
    Given default config:
      | tau        | 0.75 |
      | epsilon    | 0.05 |
      | gamma_noa  | 0.10 |
      | gamma_und  | 0.10 |
      | alpha      | 1.00 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And reasoning mode is "explore"
    And reasoning profile is "forecasting"
    And historical calibration status is "unvalidated"
    And forecasting confidence hard cap is 0.55
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.80 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.78 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.76 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.45 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.44 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.42 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then stop_reason is "FRONTIER_CONFIDENT"
    And root "H_YES" has k_root <= 0.55
    And root "H_NO" has k_root <= 0.55
    And the audit log records event "CLOSURE_TARGET_ADJUSTED_FOR_POLICY"
    And audit event "CLOSURE_TARGET_ADJUSTED_FOR_POLICY" payload includes:
      | field        |
      | tau_config   |
      | tau_effective|
      | mode         |

  # Benefit: "no legal op" is split into an epistemic outcome that means
  # "investigation completed under current model limits but confidence target
  # unmet", rather than a generic scheduler failure.
  Scenario: Epistemic exhaustion is distinguished from confidence closure
    Given default config:
      | tau        | 0.95 |
      | epsilon    | 0.05 |
      | gamma_noa  | 0.10 |
      | gamma_und  | 0.10 |
      | alpha      | 1.00 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And reasoning mode is "certify"
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.80 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.78 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.76 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.45 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.44 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.42 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then stop_reason is "EPISTEMICALLY_EXHAUSTED"
    And the audit log records event "EPISTEMIC_LIMIT_REACHED"

