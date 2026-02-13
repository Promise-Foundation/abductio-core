# tests/bdd/features/16_simple_claim_interface.feature
Feature: Simplified single-claim interface
  The framework should support an easy interface where a user enters one claim
  and receives an opinion with credence/confidence from automatic decomposition.

  Scenario: Simplified interface returns a YES opinion when evidence favors the claim
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "The UK economy will grow next year"
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                   | p    | A | B | C | D | evidence_ids |
      | H_YES:availability         | 0.85 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features  | 0.80 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance  | 0.82 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability          | 0.30 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features   | 0.35 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance   | 0.40 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then the session contains root "H_YES"
    And the session contains root "H_NO"
    And the session contains root "H_UND"
    And each root has exactly the required template slots
    And the top ledger root is "H_YES"
    And the simplified metadata records claim "The UK economy will grow next year"
    And the simplified opinion label is "YES"
    And the simplified opinion root_id is "H_YES"

  Scenario: Simplified interface returns UNDERDETERMINED when competing roots remain tied
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "The UK economy will grow next year"
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                   | p    | A | B | C | D | evidence_ids |
      | H_YES:availability         | 0.50 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features  | 0.50 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance  | 0.50 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability          | 0.50 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features   | 0.50 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance   | 0.50 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then the simplified metadata records claim "The UK economy will grow next year"
    And the simplified opinion label is "UNDERDETERMINED"
    And the simplified opinion root_id is "H_UND"
