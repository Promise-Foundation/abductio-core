# tests/bdd/features/12_parent_k_propagation.feature
Feature: Deterministic parent confidence propagation from decomposed children
  When a slot is decomposed, parent confidence (k) must be derived from children
  deterministically and then reflected in root k_root.

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
      | slot_key     | role |
      | availability | NEC  |

  Scenario: AND propagation sets parent k to min child k
    Given a scoped root "H1"
    And a deterministic decomposer that will decompose slot "H1:availability" as AND with coupling 0.80 into:
      | child_id | statement | role |
      | c1       | Child 1   | NEC  |
      | c2       | Child 2   | NEC  |
      | c3       | Child 3   | NEC  |
    And a deterministic evaluator with the following outcomes:
      | node_key            | p    | A | B | C | D | evidence_ids |
      | H1:availability:c1  | 0.90 | 2 | 2 | 2 | 2 | ref1         |
      | H1:availability:c2  | 0.80 | 2 | 1 | 1 | 0 | ref2         |
      | H1:availability:c3  | 0.70 | 1 | 1 | 0 | 0 | ref3         |
    And credits 3
    When I run the engine for exactly 3 evaluations targeting those children
    Then slot "H1:availability" has aggregated k = 0.35
    And root "H1" has k_root = 0.35
    And the audit log records parent-k propagation for "H1:availability" using rule "AND_MIN_K"

  Scenario: OR propagation uses max-p child and canonical tie-break
    Given a scoped root "H1"
    And a deterministic decomposer that will decompose slot "H1:availability" as OR with coupling 0.80 into:
      | child_id | role |
      | a        | EVID |
      | b        | EVID |
    And a deterministic evaluator with the following outcomes:
      | node_key           | p    | A | B | C | D | evidence_ids |
      | H1:availability:a  | 0.80 | 1 | 1 | 0 | 0 | ref1         |
      | H1:availability:b  | 0.80 | 2 | 2 | 2 | 2 | ref2         |
    And credits 2
    When I run the engine for exactly 2 evaluations targeting those children
    Then slot "H1:availability" has aggregated k = 0.35
    And the audit log records parent-k propagation for "H1:availability" using rule "OR_MAX_P_TIEBREAK"
    And the audit log records parent-k decisive child "H1:availability:a" for "H1:availability"

  Scenario: UNSCOPED child in decomposition caps parent k at 0.40
    Given a scoped root "H1"
    And a deterministic decomposer that will decompose slot "H1:availability" as AND with coupling 0.80 into:
      | child_id | statement | role      |
      | c1       | Child 1   | UNSCOPED  |
      | c2       | Child 2   | NEC       |
    And a deterministic evaluator with the following outcomes:
      | node_key            | p    | A | B | C | D | evidence_ids |
      | H1:availability:c1  | 0.95 | 2 | 2 | 2 | 2 | ref1         |
      | H1:availability:c2  | 0.90 | 2 | 2 | 2 | 2 | ref2         |
    And credits 2
    When I run the engine for exactly 2 evaluations targeting those children
    Then slot "H1:availability" has aggregated k = 0.40
    And root "H1" has k_root = 0.40
    And the audit log records that parent-k unscoped cap was applied for "H1:availability"

  Scenario: Guardrail signal on decisive OR child is propagated
    Given a scoped root "H1"
    And a deterministic decomposer that will decompose slot "H1:availability" as OR with coupling 0.80 into:
      | child_id | statement | role |
      | c1       | Child 1   | EVID |
      | c2       | Child 2   | EVID |
    And a deterministic evaluator with the following outcomes:
      | node_key            | p    | A | B | C | D | evidence_ids |
      | H1:availability:c1  | 0.90 | 2 | 1 | 1 | 0 | ref1         |
      | H1:availability:c2  | 0.80 | 2 | 2 | 2 | 2 | ref2         |
    And credits 2
    When I run the engine for exactly 2 evaluations targeting those children
    Then slot "H1:availability" has aggregated k = 0.55
    And the audit log records that parent-k guardrail signal was detected for "H1:availability"
