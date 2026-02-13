# tests/bdd/features/30_active_set_adjudication_closure_enforcement.feature
Feature: Active-set adjudication closure enforcement
  # This feature requires closure checks to use the decision-relevant active
  # contender frontier, not only static/global pairwise assumptions.

  # Benefit: a run cannot claim confident closure when top contenders have not
  # been contrastively adjudicated against each other.
  Scenario: Closure is deferred when active-set pairwise adjudication is incomplete
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
      | root_a | root_b | discriminator                      |
      | H1     | H2     | Observable X separates H1 from H2 |
      | H1     | H3     | Observable X separates H1 from H3 |
      | H1     | H4     | Observable X separates H1 from H4 |
      | H2     | H3     | Observable X separates H2 from H3 |
      | H2     | H4     | Observable X separates H2 from H4 |
      | H3     | H4     | Observable X separates H3 from H4 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And active-set closure adjudication is required
    And closure active-set contender count is 3
    And closure active-set contender mass ratio floor is 0.00
    And closure minimum pairwise coverage ratio is 1.00
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a scoped root "H4"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS  |
      | H2:availability | 0.60 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                      | false              | SUPPORTS  |
      | H3:availability | 0.58 | 2 | 2 | 2 | 2 | ref3         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
      | H4:availability | 0.10 | 2 | 2 | 2 | 2 | ref4         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
    And credits 6
    When I run the engine until it stops
    Then stop_reason is "CLOSURE_GATES_UNMET"
    And the audit log records event "FRONTIER_CONFIDENCE_DEFERRED"
    And the audit log records event "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED"
    And the audit log records event "CLOSURE_ACTIVE_SET_ADJUDICATION_INCOMPLETE"
    And audit event "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED" payload field "status" equals "FAILED"
    And audit event "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED" payload field "pairwise_scope" equals "active_set"

  # Benefit: once active-set pairs are observed with typed discriminators,
  # closure can proceed without requiring global all-pairs adjudication.
  Scenario: Closure proceeds when active-set adjudication is complete
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
      | root_a | root_b | discriminator                      |
      | H1     | H2     | Observable X separates H1 from H2 |
      | H1     | H3     | Observable X separates H1 from H3 |
      | H1     | H4     | Observable X separates H1 from H4 |
      | H2     | H3     | Observable X separates H2 from H3 |
      | H2     | H4     | Observable X separates H2 from H4 |
      | H3     | H4     | Observable X separates H3 from H4 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And active-set closure adjudication is required
    And closure active-set contender count is 3
    And closure active-set contender mass ratio floor is 0.00
    And closure minimum pairwise coverage ratio is 1.00
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a scoped root "H4"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                                                                                                                                                     | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                                                                                                                                                          | false              | SUPPORTS  |
      | H2:availability | 0.60 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                                                                                                                                                          | false              | SUPPORTS  |
      | H3:availability | 0.58 | 2 | 2 | 2 | 2 | ref3         | d13,d23           | [{"id":"d13","pair":"H1/H3","direction":"FAVORS_LEFT","evidence_ids":["ref3"]},{"id":"d23","pair":"H2/H3","direction":"FAVORS_LEFT","evidence_ids":["ref3"]}]                                                                          | false              | SUPPORTS  |
      | H4:availability | 0.10 | 2 | 2 | 2 | 2 | ref4         | (empty)           | []                                                                                                                                                                                                                                         | true               | SUPPORTS  |
    And credits 6
    When I run the engine until it stops
    Then stop_reason is "FRONTIER_CONFIDENT"
    And the audit log records event "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED"
    And the audit log does not record event "CLOSURE_ACTIVE_SET_ADJUDICATION_INCOMPLETE"
    And audit event "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED" payload field "status" equals "PASSED"
    And audit event "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED" payload field "pairwise_scope" equals "active_set"
