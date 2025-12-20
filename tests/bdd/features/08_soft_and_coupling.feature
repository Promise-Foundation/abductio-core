# tests/bdd/features/08_soft_and_coupling.feature
Feature: Soft-AND aggregation with coupling buckets
  Within-slot AND of NEC children must use the coupling rule:
    m = c * p_min + (1-c) * p_prod
  treating unassessed NEC children as p=1.0.

  Background:
    Given required template slots:
      | slot_key            | role |
      | feasibility         | NEC  |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |

  Scenario Outline: Soft-AND matches the specified formula for assessed children
    Given a scoped root "H1" with slot "fit_to_key_features" decomposed as AND coupling <c> into NEC children:
      | child_id | statement |
      | c1       | Part 1    |
      | c2       | Part 2    |
    And a deterministic evaluator that returns:
      | node_key | p   | A | B | C | D | evidence_refs |
      | H1:fit:c1| <p1>| 2 | 1 | 1 | 1 | refX         |
      | H1:fit:c2| <p2>| 2 | 1 | 1 | 1 | refX         |
    And credits 2
    When I run the engine for exactly 2 evaluations targeting those children
    Then the aggregated p for slot "H1:fit_to_key_features" equals <expected> within 1e-9
    And the audit log shows p_min, p_prod, c, and the computed m

    Examples:
      | c    | p1  | p2  | expected |
      # min=0.5 prod=0.25 => 0.2*0.5 + 0.8*0.25 = 0.1 + 0.2 = 0.3
      | 0.20 | 0.5 | 0.5 | 0.30     |
      | 0.80 | 0.7 | 0.9 | 0.686    |

  Scenario: Unassessed NEC children are treated as p=1.0
    Given a scoped root "H1" with slot "fit_to_key_features" decomposed as AND coupling 0.80 into NEC children:
      | child_id | statement |
      | c1       | Part 1    |
      | c2       | Part 2    |
      | c3       | Part 3    |
    And only child "c1" is evaluated with p=0.5 and evidence_refs "ref1"
    And credits 1
    When I run the engine for exactly 1 evaluation
    Then unassessed children "c2" and "c3" are treated as p=1.0 in aggregation
    And the aggregated slot p is <= 0.5 and >= 0.5 * 1.0 * 1.0
