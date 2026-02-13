# tests/bdd/features/06_deterministic_scheduling_and_frontier.feature
Feature: Deterministic scheduling, frontier selection, and tie-breaking
  Scheduling must be seed-invariant: no focal injection, canonical ordering by hash(statement),
  and round-robin credit slices over the frontier.

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
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |

  Scenario: Frontier is defined purely from p_ledger and epsilon (no focal injection)
    Given a hypothesis set with named roots:
      | id   | statement       | exclusion_clause                |
      | H1   | Mechanism A     | Not explained by any other root |
      | H2   | Mechanism B     | Not explained by any other root |
      | H3   | Mechanism C     | Not explained by any other root |
    And the ledger is set to:
      | id | p_ledger |
      | H1 | 0.30     |
      | H2 | 0.28     |
      | H3 | 0.10     |
      | H_NOA | 0.16 |
      | H_UND | 0.16 |
    And epsilon = 0.05
    And credits 1
    When I run the engine for exactly 1 operation
    Then the frontier contains exactly {"H1","H2"}
    And the audit log records the leader and the frontier definition

  Scenario: Within a cycle, frontier is iterated in canonical order, not input order
    Given a hypothesis set with named roots:
      | id   | statement       | exclusion_clause                |
      | H9   | Zeta mechanism  | Not explained by any other root |
      | H1   | Alpha mechanism | Not explained by any other root |
    And the ledger is set to:
      | id | p_ledger |
      | H9 | 0.30     |
      | H1 | 0.30     |
      | H_NOA | 0.20 |
      | H_UND | 0.20 |
    And credits 2
    When I run the engine for exactly 2 operations
    Then the operation order follows canonical_id order of statements, not the provided ids
    And the audit log shows deterministic tie-breaking

  Scenario: Evaluate-before-deepen is enforced after root scoping
    Given a hypothesis set with named roots:
      | id | statement       | exclusion_clause                |
      | H1 | Alpha mechanism | Not explained by any other root |
    And a deterministic decomposer that will scope root "H1"
    And a deterministic decomposer that will decompose slot "H1:availability" as AND with coupling 0.80 into:
      | child_id | statement      | role |
      | c1       | Avail signal 1 | NEC  |
      | c2       | Avail signal 2 | NEC  |
    And a deterministic decomposer that will decompose slot "H1:fit_to_key_features" as AND with coupling 0.80 into:
      | child_id | statement    | role |
      | c1       | Fit signal 1 | NEC  |
      | c2       | Fit signal 2 | NEC  |
    And a deterministic evaluator with the following outcomes:
      | node_key                 | p    | A | B | C | D | evidence_ids |
      | H1:availability          | 0.60 | 2 | 1 | 1 | 1 | ref1         |
      | H1:fit_to_key_features   | 0.60 | 2 | 1 | 1 | 1 | ref2         |
      | H1:defeater_resistance   | 0.60 | 2 | 1 | 1 | 1 | ref3         |
    And credits 4
    When I run the engine for exactly 4 operations
    Then operation 1 is "DECOMPOSE" targeting "H1"
    And operation 2 is "EVALUATE" targeting "H1:availability"
    And operation 3 is "EVALUATE" targeting "H1:fit_to_key_features"
    And operation 4 is "EVALUATE" targeting "H1:defeater_resistance"
    And no slot-level decomposition occurs before all required slots of "H1" are first evaluated
