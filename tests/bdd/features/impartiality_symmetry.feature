@impartiality @abductio @fairness
Feature: Symmetric evaluation prevents focal privilege and framing bias
  As a diligence user
  I want all competing hypotheses to face the same obligations
  So that the system does not privilege one narrative by default

  Background:
    Given default config:
      | tau        | 0.70 |
      | epsilon    | 0.05 |
      | gamma      | 0.20 |
      | alpha      | 0.40 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |

  Scenario: All roots are instantiated with the same required slots
    Given a hypothesis set with named roots:
      | id     | statement      | exclusion_clause                |
      | H_PASS | Pass mechanism | Not explained by any other root |
      | H_FAIL | Fail mechanism | Not explained by any other root |
    And a deterministic decomposer that will scope all roots
    And credits 2
    When I run the engine for exactly 2 operations
    Then each root has exactly the required template slots
    And the required slots under "H_PASS" and "H_FAIL" are identical

  Scenario: Reordering roots does not change results
    Given hypothesis set A with named roots:
      | id     | statement      | exclusion_clause                |
      | H_PASS | Pass mechanism | Not explained by any other root |
      | H_FAIL | Fail mechanism | Not explained by any other root |
    And hypothesis set B with the same roots but reversed ordering
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                   | p    | A | B | C | D | evidence_ids |
      | H_PASS:availability        | 0.60 | 2 | 1 | 1 | 1 | ref2         |
      | H_FAIL:availability        | 0.60 | 2 | 1 | 1 | 1 | ref2         |
      | H_PASS:fit_to_key_features | 0.60 | 2 | 1 | 1 | 1 | ref3         |
      | H_FAIL:fit_to_key_features | 0.60 | 2 | 1 | 1 | 1 | ref3         |
      | H_PASS:defeater_resistance | 0.60 | 2 | 1 | 1 | 1 | ref4         |
      | H_FAIL:defeater_resistance | 0.60 | 2 | 1 | 1 | 1 | ref4         |
    And credits 20
    When I run the engine on hypothesis set A until it stops
    And I run the engine on hypothesis set B until it stops
    Then the final p_ledger and k_root for each named root are identical within 1e-9
    And the final H_NOA and H_UND p_ledger are identical within 1e-9
    And the sequence of executed operations is identical when compared by canonical target_id

  Scenario: Evaluation is invariant to prompt framing when evidence is unchanged
    Given a hypothesis set with named roots:
      | id     | statement      | exclusion_clause                |
      | H_PASS | Pass mechanism | Not explained by any other root |
      | H_FAIL | Fail mechanism | Not explained by any other root |
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                   | p    | A | B | C | D | evidence_ids |
      | H_PASS:availability        | 0.60 | 2 | 1 | 1 | 1 | ref2         |
      | H_FAIL:availability        | 0.60 | 2 | 1 | 1 | 1 | ref2         |
      | H_PASS:fit_to_key_features | 0.60 | 2 | 1 | 1 | 1 | ref3         |
      | H_FAIL:fit_to_key_features | 0.60 | 2 | 1 | 1 | 1 | ref3         |
      | H_PASS:defeater_resistance | 0.60 | 2 | 1 | 1 | 1 | ref4         |
      | H_FAIL:defeater_resistance | 0.60 | 2 | 1 | 1 | 1 | ref4         |
    And credits 20
    When I run the engine with framing text "assume it passes unless proven otherwise" until it stops
    And I run the engine with framing text "assume it fails unless proven otherwise" until it stops
    Then the required slots under "H_PASS" and "H_FAIL" are identical
    And the sequence of executed operations is identical when compared by canonical target_id

  Scenario: Weakest-slot explanation is reported for each root
    Given a hypothesis set with named roots:
      | id     | statement      | exclusion_clause                |
      | H_PASS | Pass mechanism | Not explained by any other root |
      | H_FAIL | Fail mechanism | Not explained by any other root |
    And a deterministic decomposer that will scope all roots
    And credits 2
    When I run the engine for exactly 2 operations
    Then root "H_PASS" includes a weakest_slot field
    And root "H_FAIL" includes a weakest_slot field
