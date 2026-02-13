# tests/bdd/features/21_next_step_guidance.feature
Feature: Assumption-focused next-step guidance
  # This feature ensures the engine returns actionable investigation guidance
  # instead of only a scalar confidence outcome.

  # Benefit: users can inspect which assumptions and sub-claims are bottlenecking
  # confidence and know what evidence would most improve the model.
  Scenario: Epistemic exhaustion returns slot-level next-step guidance
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
    And slot assumptions for root "H_YES" are all:
      | assumption_id        |
      | fiscal_policy_stable |
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
    And the simplified metadata includes at least 1 next-step recommendation
    And the simplified next-step guidance includes root "H_YES" slot "availability"
    And the simplified next-step guidance references assumption "fiscal_policy_stable"
    And the audit log records event "NEXT_STEPS_GENERATED"

