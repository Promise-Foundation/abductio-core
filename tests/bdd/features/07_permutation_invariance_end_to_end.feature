# tests/bdd/features/07_permutation_invariance_end_to_end.feature
Feature: Permutation invariance (end-to-end)
  Given identical inputs, outputs must be identical (up to ordering) regardless of hypothesis list permutation.

  Background:
    Given default config:
      | tau     | 0.70 |
      | epsilon | 0.05 |
      | gamma   | 0.20 |
      | alpha   | 0.40 |
      | beta    | 1.00 |
      | W       | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | feasibility         | NEC  |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                         | p    | A | B | C | D | evidence_ids |
      | H1:feasibility                   | 0.80 | 2 | 1 | 1 | 1 | ref1          |
      | H2:feasibility                   | 0.70 | 2 | 1 | 1 | 1 | ref1          |
      | H1:availability                  | 0.60 | 2 | 1 | 1 | 1 | ref2          |
      | H2:availability                  | 0.90 | 2 | 1 | 1 | 1 | ref2          |
      | H1:fit_to_key_features           | 0.75 | 2 | 1 | 1 | 1 | ref3          |
      | H2:fit_to_key_features           | 0.65 | 2 | 1 | 1 | 1 | ref3          |
      | H1:defeater_resistance           | 0.55 | 2 | 1 | 1 | 1 | ref4          |
      | H2:defeater_resistance           | 0.85 | 2 | 1 | 1 | 1 | ref4          |

  Scenario: Final ledger is invariant under input ordering
    Given hypothesis set A with named roots:
      | id   | statement     | exclusion_clause                |
      | H1   | Mechanism A   | Not explained by any other root |
      | H2   | Mechanism B   | Not explained by any other root |
    And hypothesis set B with the same roots but reversed ordering
    And credits 20
    When I run the engine on hypothesis set A until it stops
    And I run the engine on hypothesis set B until it stops
    Then the final p_ledger and k_root for each named root are identical within 1e-9
    And the final H_other p_ledger is identical within 1e-9
    And the sequence of executed operations is identical when compared by canonical target_id
