# tests/bdd/features/27_active_set_decision_certification.feature
Feature: Active-set decision certification
  # This feature constrains strict pairwise certification to the
  # decision-relevant contender frontier instead of all pair combinations.

  # Benefit: preserves contrastive rigor while avoiding combinatorial stalls
  # when many low-probability alternatives are present.
  Scenario: Decision contract passes when active contender set is fully adjudicated
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
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
      | H1     | H3     | Observable X separates H1 from H3 |
      | H1     | H4     | Observable X separates H1 from H4 |
      | H2     | H3     | Observable X separates H2 from H3 |
      | H2     | H4     | Observable X separates H2 from H4 |
      | H3     | H4     | Observable X separates H3 from H4 |
    And strict contrastive updates are required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.00
    And active-set decision certification is enabled
    And active-set contender count is 2
    And typed discriminator evidence is required
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment  |
      | H1:availability | 0.95 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS   |
      | H2:availability | 0.75 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                      | false              | SUPPORTS   |
      | H3:availability | 0.10 | 2 | 2 | 2 | 2 | ref3         | (empty)           | []                                                                                                     | true               | SUPPORTS   |
      | H4:availability | 0.10 | 2 | 2 | 2 | 2 | ref4         | (empty)           | []                                                                                                     | true               | SUPPORTS   |
    And credits 6
    When I run the engine until credits exhausted
    Then the audit log records event "DECISION_ACTIVE_SET_SELECTED"
    And the audit log records event "DECISION_CONTRACT_PASSED"
    And the audit log does not record event "DECISION_CONTRACT_FAILED"
    And audit event "DECISION_CONTRACT_PASSED" payload field "pairwise_scope" equals "active_set"

  # Benefit: active-set mode still blocks closure when unresolved contrastive
  # uncertainty remains inside the contender frontier.
  Scenario: Decision contract fails when active contender set is not fully adjudicated
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
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
      | H1     | H3     | Observable X separates H1 from H3 |
      | H1     | H4     | Observable X separates H1 from H4 |
      | H2     | H3     | Observable X separates H2 from H3 |
      | H2     | H4     | Observable X separates H2 from H4 |
      | H3     | H4     | Observable X separates H3 from H4 |
    And strict contrastive updates are required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.00
    And active-set decision certification is enabled
    And active-set contender count is 3
    And typed discriminator evidence is required
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS  |
      | H2:availability | 0.40 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                      | false              | SUPPORTS  |
      | H3:availability | 0.39 | 2 | 2 | 2 | 2 | ref3         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
      | H4:availability | 0.05 | 2 | 2 | 2 | 2 | ref4         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
    And credits 6
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "DECISION_ACTIVE_SET_SELECTED"
    And the audit log records event "DECISION_CONTRACT_FAILED"
    And audit event "DECISION_CONTRACT_FAILED" payload field "pairwise_scope" equals "active_set"
    And audit event "DECISION_CONTRACT_FAILED" payload includes:
      | field                |
      | active_set_roots     |
      | active_set_pair_count |
      | failing_conditions   |
