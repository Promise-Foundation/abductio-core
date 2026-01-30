Feature: Evidence search as a first-class operation
  ABDUCTIO may perform replayable evidence search under symmetric, credit-metered rules.

  Background:
    Given default config:
      | tau         | 0.7  |
      | epsilon     | 0.05 |
      | gamma       | 0.2  |
      | alpha       | 0.4  |
      | beta        | 1.0  |
      | W           | 3.0  |
      | lambda_voi  | 0.1  |
      | world_mode  | open |
    And required template slots:
      | slot_key           | role |
      | availability       | NEC  |
      | fit_to_key_features| NEC  |
      | defeater_resistance| NEC  |
    And a hypothesis set with named roots:
      | id | statement                    | exclusion_clause |
      | H1 | Churn is product-driven      | Not explained by any other root |
      | H2 | Churn is primarily price-driven | Not explained by any other root |
    And credits 12

  Scenario: Search operations are logged and credit-metered
    Given evidence search is enabled with max depth 2 and per-node quota 1
    When I run the engine
    Then the audit log includes SEARCH operations
    And each SEARCH operation records a search snapshot hash
    And each SEARCH operation records an evidence packet hash

  Scenario: Search quotas are symmetric across hypotheses per slot
    Given evidence search is enabled with per-slot quota 1
    When I run the engine
    Then search credits for slot "availability" are equal across hypotheses
    And search credits for slot "fit_to_key_features" are equal across hypotheses
    And search credits for slot "defeater_resistance" are equal across hypotheses

  Scenario: Search is replayable and non-adaptive to interim scores
    Given evidence search is enabled with deterministic queries
    When I run the engine
    Then search queries are derived from scope, hypothesis, slot, and depth
    And search budgets do not change based on interim ledger scores
