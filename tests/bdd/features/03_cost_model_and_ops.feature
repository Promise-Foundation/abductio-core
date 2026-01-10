# tests/bdd/features/03_cost_model_and_ops.feature
Feature: Cost model and operation legality
  Only two operations exist (DECOMPOSE, EVALUATE), each costs exactly 1 credit.
  The engine must halt by the specified stopping conditions.

  Background:
    Given default config:
      | tau     | 0.70 |
      | epsilon | 0.05 |
      | gamma   | 0.20 |
      | alpha   | 0.40 |
      | beta    | 1.00 |
      | W       | 3.00 |
      | lambda_voi | 0.10 |

  Scenario: Each operation spends exactly 1 credit and is audited
    Given a hypothesis set with named roots:
      | id   | statement          | exclusion_clause                |
      | H1   | Mechanism A        | Not explained by any other root |
    And a deterministic decomposer that will scope roots with:
      | root_id | feasibility_statement    | availability_statement | fit_statement         | defeater_statement      |
      | H1      | A possible              | A available           | A fits               | A resists defeater     |
    And a deterministic evaluator that returns for node "H1:feasibility":
      | p | 0.90 |
      | A | 2    |
      | B | 1    |
      | C | 1    |
      | D | 1    |
      | evidence_ids | ref1 |
    And credits 2
    When I run the engine until credits exhausted
    Then total_credits_spent = 2
    And the audit log contains exactly 2 operation records
    And each operation record includes: op_type, target_id, credits_before, credits_after

  Scenario: Stop condition A (credits exhausted) is respected
    Given a hypothesis set with named roots:
      | id   | statement          | exclusion_clause                |
      | H1   | Mechanism A        | Not explained by any other root |
      | H2   | Mechanism B        | Not explained by any other root |
    And credits 0
    When I start a session for scope "Test scope"
    Then stop_reason is "CREDITS_EXHAUSTED"
    And no operations were executed

  Scenario: Stop condition B (frontier all meet tau) is respected
    Given required template slots:
      | slot_key            | role |
      | feasibility         | NEC  |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    Given a hypothesis set with named roots:
      | id   | statement          | exclusion_clause                |
      | H1   | Mechanism A        | Not explained by any other root |
    And the root "H1" is already SCOPED with all slots having k >= 0.70
    And credits 10
    When I run the engine until it stops
    Then stop_reason is "FRONTIER_CONFIDENT"
    And credits_remaining = 10
