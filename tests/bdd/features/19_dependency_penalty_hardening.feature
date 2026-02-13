# tests/bdd/features/19_dependency_penalty_hardening.feature
Feature: Evidence dependency and shared-assumption hardening
  # This feature prevents confidence inflation from repeatedly counting the
  # same evidence source or the same hidden assumption as independent support.

  # Benefit: if all "support" comes from one correlated source, confidence is
  # explicitly discounted rather than treated as three independent confirmations.
  Scenario: Shared-source overlap applies dependency penalty to root confidence
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And evidence dependency overlap threshold is 0.50
    And dependency-penalty confidence cap is 0.55
    And all supporting evidence for root "H_YES" originates from source "single_forecast_note"
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.84 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.83 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.82 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.38 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.36 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.35 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then root "H_YES" has k_root <= 0.55
    And the audit log records event "EVIDENCE_DEPENDENCY_PENALTY_APPLIED"
    And the audit log records dependency overlap score for root "H_YES" >= 0.50

  # Benefit: repeated assumptions ("if X is true then all slots pass") are
  # handled as a single fragile support channel, not multiple robust supports.
  Scenario: Shared assumptions across slots cap confidence despite high slot scores
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And assumption-overlap confidence cap is 0.55
    And slot assumptions for root "H_YES" are all:
      | assumption_id        |
      | fiscal_policy_stable |
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.78 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.80 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.76 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.44 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.45 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.43 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then root "H_YES" has k_root <= 0.55
    And the audit log records event "ASSUMPTION_DEPENDENCY_PENALTY_APPLIED"
    And the audit log records assumption overlap score for root "H_YES" >= 0.50

