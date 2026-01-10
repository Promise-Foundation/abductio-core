# tests/bdd/features/11_auditability_and_replay.feature
Feature: Full auditability and deterministic replay
  Every arithmetic update and invariant check must be logged so a run can be replayed to identical results.

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

  Scenario: Audit trace includes load-bearing computations
    Given a hypothesis set with named roots:
      | id   | statement     | exclusion_clause                |
      | H1   | Mechanism A   | Not explained by any other root |
      | H2   | Mechanism B   | Not explained by any other root |
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with at least one evaluation outcome
    And credits 5
    When I run the engine until it stops
    Then the audit trace contains entries for:
      | event_type |
      | OP_EXECUTED |
      | MULTIPLIER_COMPUTED |
      | P_PROP_COMPUTED |
      | DAMPING_APPLIED |
      | OTHER_ABSORBER_ENFORCED |
      | INVARIANT_SUM_TO_ONE_CHECK |
      | STOP_REASON_RECORDED |
    And every numeric value used in ledger updates is recorded with sufficient precision

  Scenario: Replay from audit produces identical final ledger
    Given I ran a session and captured its audit trace
    When I replay the session using only the audit trace as the source of operations and numeric outcomes
    Then the replayed final p_ledger values equal the original final p_ledger values within 1e-12
    And the replayed stop_reason equals the original stop_reason
