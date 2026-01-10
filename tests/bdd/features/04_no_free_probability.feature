# tests/bdd/features/04_no_free_probability.feature
Feature: No-free-probability semantics
  Decomposition must not create or destroy ledger probability by itself.
  Unassessed NEC nodes must default to neutral p=0.5 so listing more requirements does not penalize.

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

  Scenario: Scoping (template instantiation) alone does not change ledger probabilities
    Given a hypothesis set with named roots:
      | id   | statement     | exclusion_clause                |
      | H1   | Mechanism A   | Not explained by any other root |
      | H2   | Mechanism B   | Not explained by any other root |
    And a deterministic decomposer that will scope all roots
    And credits 2
    When I run the engine for exactly 2 operations
    Then all named roots are SCOPED
    And each named root p_ledger is unchanged from its initial value within 1e-9
    And H_other p_ledger is unchanged from its initial value within 1e-9

  Scenario: Adding additional NEC children inside a slot does not penalize until evaluated
    Given a hypothesis set with named roots:
      | id   | statement     | exclusion_clause                |
      | H1   | Mechanism A   | Not explained by any other root |
    And a deterministic decomposer that will scope root "H1"
    And a deterministic decomposer that will decompose slot "H1:fit_to_key_features" as AND with coupling 0.80 into:
      | child_id | statement                 | role |
      | c1       | Fits timing               | NEC  |
      | c2       | Fits witness consistency  | NEC  |
      | c3       | Fits physical traces      | NEC  |
    And credits 2
    When I run the engine for exactly 2 operations
    Then slot "H1:fit_to_key_features" has aggregated p = 0.5
    And no ledger probability changed due to unassessed NEC children
