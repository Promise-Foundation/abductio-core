# tests/bdd/features/34_budget_feasible_pair_adjudication.feature
Feature: Budget-feasible pair adjudication and coverage accounting
  # Benefit: closure/decision contracts must be feasible under finite credits.
  # If the active set implies more pairs than the adjudication budget can cover,
  # the active set is capped to a size whose pair count is budget-feasible.
  Scenario: Pair-adjudication active set is capped by pair budget
    Given default config:
      | tau        | 0.75 |
      | epsilon    | 0.05 |
      | gamma_noa  | 0.10 |
      | gamma_und  | 0.10 |
      | alpha      | 1.00 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key     | role |
      | availability | NEC  |
    Given a hypothesis set with named roots:
      | id | statement       | exclusion_clause                |
      | H1 | Mechanism Alpha | Not explained by any other root |
      | H2 | Mechanism Beta  | Not explained by any other root |
      | H3 | Mechanism Gamma | Not explained by any other root |
      | H4 | Mechanism Delta | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H1     | H4     | 1     |
      | H2     | H3     | 1     |
      | H2     | H4     | 1     |
      | H3     | H4     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                       |
      | H1     | H2     | Observable X separates H1 from H2  |
      | H1     | H3     | Observable X separates H1 from H3  |
      | H1     | H4     | Observable X separates H1 from H4  |
      | H2     | H3     | Observable X separates H2 from H3  |
      | H2     | H4     | Observable X separates H2 from H4  |
      | H3     | H4     | Observable X separates H3 from H4  |
    And strict contrastive updates are required
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 4
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And pair-adjudication pair budget is 3
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a scoped root "H4"
    And credits 1
    When I run the engine for exactly 1 operation
    Then the audit log records event "PAIR_ADJUDICATION_QUEUE_UPDATED"
    And audit event "PAIR_ADJUDICATION_QUEUE_UPDATED" payload field "active_set_pair_count" equals "3"
    And audit event "PAIR_ADJUDICATION_QUEUE_UPDATED" payload field "pair_count" equals "3"
    And audit event "PAIR_ADJUDICATION_QUEUE_UPDATED" payload field "theoretical_pair_count" equals "3"

  # Benefit: unresolved-pair pressure for abstention should be computed against
  # feasible pairs, not the full theoretical pair graph that exceeds budget.
  Scenario: Dynamic abstention unresolved ratio uses feasible pair denominator
    Given default config:
      | tau        | 0.90 |
      | epsilon    | 0.05 |
      | gamma_noa  | 0.10 |
      | gamma_und  | 0.10 |
      | alpha      | 1.00 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key     | role |
      | availability | NEC  |
    Given a hypothesis set with named roots:
      | id | statement       | exclusion_clause                |
      | H1 | Mechanism Alpha | Not explained by any other root |
      | H2 | Mechanism Beta  | Not explained by any other root |
      | H3 | Mechanism Gamma | Not explained by any other root |
      | H4 | Mechanism Delta | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H1     | H4     | 1     |
      | H2     | H3     | 1     |
      | H2     | H4     | 1     |
      | H3     | H4     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                       |
      | H1     | H2     | Observable X separates H1 from H2  |
      | H1     | H3     | Observable X separates H1 from H3  |
      | H1     | H4     | Observable X separates H1 from H4  |
      | H2     | H3     | Observable X separates H2 from H3  |
      | H2     | H4     | Observable X separates H2 from H4  |
      | H3     | H4     | Observable X separates H3 from H4  |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And dynamic abstention mass is enabled
    And dynamic abstention unresolved-pair weight is 0.30
    And dynamic abstention contradiction-density weight is 0.00
    And dynamic abstention non-discriminative weight is 0.00
    And dynamic abstention mass minimum is 0.10
    And dynamic abstention mass maximum is 0.90
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 4
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And pair-adjudication pair budget is 3
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                          |
      | p                      | 0.80                                                                           |
      | A                      | 2                                                                              |
      | B                      | 2                                                                              |
      | C                      | 2                                                                              |
      | D                      | 2                                                                              |
      | evidence_ids           | ref1                                                                           |
      | discriminator_ids      | d12                                                                            |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}] |
      | non_discriminative     | false                                                                          |
      | entailment             | SUPPORTS                                                                       |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "ABSTENTION_MASS_DYNAMIC_UPDATED"
    And audit event "ABSTENTION_MASS_DYNAMIC_UPDATED" payload field "unresolved_pair_ratio" is at least 0.60
    And audit event "ABSTENTION_MASS_DYNAMIC_UPDATED" payload field "unresolved_pair_ratio" is at most 0.70
    And root "H_UND" has p_ledger >= 0.29
