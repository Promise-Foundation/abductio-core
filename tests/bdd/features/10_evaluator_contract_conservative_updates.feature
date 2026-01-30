# tests/bdd/features/10_evaluator_contract_conservative_updates.feature
Feature: Evaluator contract enforcement (conservative update with no evidence_ids)
  If evidence_ids is empty, the engine must enforce conservative movement: |Δp| <= 0.05 from prior node.p.

  Background:
    Given required template slots:
      | slot_key    | role |
      | availability | NEC  |

  Scenario: Empty evidence_ids constrains p movement
    Given a scoped root "H1"
    And slot node "H1:availability" has initial p = 1.0
    And a deterministic evaluator that attempts to set for node "H1:availability":
      | key           | value   |
      | p             | 0.20    |
      | A             | 2       |
      | B             | 2       |
      | C             | 2       |
      | D             | 2       |
      | evidence_ids | (empty) |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the stored p for "H1:availability" equals 0.95 within 1e-9
    And the audit log records that conservative delta was enforced

  Scenario: Non-empty evidence_ids allows full movement within [0,1]
    Given a scoped root "H1"
    And slot node "H1:availability" has initial p = 1.0
    And a deterministic evaluator that returns for node "H1:availability":
      | key           | value |
      | p             | 0.20  |
      | A             | 2     |
      | B             | 2     |
      | C             | 2     |
      | D             | 2     |
      | evidence_ids | ref1  |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the stored p for "H1:availability" equals 0.20 within 1e-9
