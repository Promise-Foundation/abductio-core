# tests/bdd/features/05_ledger_update_and_other_absorber.feature
Feature: Ledger updates, damping, and Other absorber invariant
  Ledger updates must be auditable, deterministic, and keep probabilities summing to 1 with H_other absorbing slack.

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

  Scenario: Evaluating a slot applies a log-space delta-w ledger update
    Given a hypothesis set with named roots:
      | id   | statement       | exclusion_clause                |
      | H1   | Mechanism A     | Not explained by any other root |
    And a deterministic decomposer that will scope root "H1"
    And a deterministic evaluator that returns for node "H1:feasibility":
      | p | 0.50 |
      | A | 2    |
      | B | 1    |
      | C | 1    |
      | D | 1    |
      | evidence_ids | ref1 |
    And credits 2
    When I run the engine until credits exhausted
    Then the audit log includes a delta-w update for root "H1" slot "feasibility"
    And the audit log includes a normalized ledger update
    And the ledger probabilities sum to 1.0 within 1e-9
    And H_other is set to 1 - sum(named_roots)

  Scenario: Engine repairs corrupted ledger using the invariant enforcement routine
    Given a hypothesis set with named roots:
      | id   | statement       | exclusion_clause                |
      | H1   | Mechanism A     | Not explained by any other root |
      | H2   | Mechanism B     | Not explained by any other root |
    And the ledger is externally corrupted so that sum(named_roots) = 1.2 and H_other = -0.2
    And credits 0
    When I start a session for scope "Invariant repair"
    Then the engine enforces the Other absorber invariant
    And all p_ledger values are in [0,1]
    And the ledger probabilities sum to 1.0 within 1e-9
    And the audit log records which branch was taken (S<=1 or S>1)
