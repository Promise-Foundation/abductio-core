# tests/bdd/features/36_active_set_churn_accounting.feature
Feature: Active-set churn accounting for pair adjudication
  # Benefit: when contender ordering shifts during a run, unresolved pair
  # adjudication should continue on the already-started active set so prior
  # adjudication work is not discarded by scope churn.

  Scenario: Sticky active-set lock preserves unresolved pair work across churn
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
    And the ledger is set to:
      | id    | p_ledger |
      | H1    | 0.36     |
      | H2    | 0.35     |
      | H3    | 0.24     |
      | H_NOA | 0.03     |
      | H_UND | 0.02     |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
      | H1     | H3     | Observable X separates H1 from H3 |
      | H2     | H3     | Observable X separates H2 from H3 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And pair-adjudication active-set lock is enabled
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.05 | 2 | 2 | 2 | 2 | ref1         | d13               | [{"id":"d13","pair":"H1/H3","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]       | false              | SUPPORTS  |
      | H2:availability | 0.05 | 2 | 2 | 2 | 2 | ref2         | d23               | [{"id":"d23","pair":"H2/H3","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]       | false              | SUPPORTS  |
      | H3:availability | 0.90 | 2 | 2 | 2 | 2 | ref3         | d13               | [{"id":"d13","pair":"H1/H3","direction":"FAVORS_RIGHT","evidence_ids":["ref3"]}]      | false              | SUPPORTS  |
    And credits 2
    When I run the engine for exactly 2 operations
    Then the audit log records event "PAIR_ADJUDICATION_ACTIVE_SET_REUSED"
    And audit events "PAIR_ADJUDICATION_ACTIVE_SET_REUSED" payload field "locked_active_set_roots" include values:
      | value |
      | H1    |
      | H2    |
    And audit events "PAIR_ADJUDICATION_ACTIVE_SET_REUSED" payload field "candidate_active_set_roots" include values:
      | value |
      | H3    |
