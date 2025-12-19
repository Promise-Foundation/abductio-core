# tests/bdd/features/09_confidence_k_rubric.feature
Feature: Confidence k rubric mapping and guardrails
  Confidence k must be derived from rubric A-D (0..2 each) using the specified mapping,
  with the guardrail: if any check = 0, cap k <= 0.55.

  Scenario Outline: Rubric totals map to k as specified
    Given a deterministic evaluator that returns rubric:
      | A | <A> |
      | B | <B> |
      | C | <C> |
      | D | <D> |
    When the engine derives k from the rubric
    Then k equals <k_expected>

    Examples:
      | A | B | C | D | k_expected |
      | 0 | 0 | 0 | 0 | 0.15       |
      | 1 | 1 | 0 | 0 | 0.35       |
      | 2 | 1 | 1 | 0 | 0.55       |  # capped if any=0 (still <=0.55)
      | 2 | 2 | 2 | 2 | 0.90       |

  Scenario: Guardrail cap is applied when any check is zero
    Given a deterministic evaluator returns:
      | A | 2 |
      | B | 2 |
      | C | 2 |
      | D | 0 |
    When the engine derives k from the rubric
    Then k <= 0.55
    And the audit log records that the guardrail cap was applied
