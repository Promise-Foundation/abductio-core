# tests/bdd/features/42_pair_resolution_adjudication_engine.feature
Feature: Pair-resolution adjudication engine
  # This feature makes pair adjudication semantic instead of binary:
  # a pair is only "resolved" when directional evidence yields a clear verdict.

  # Benefit: prevents false completion where a pair is merely touched, but still
  # ambiguous, contradictory, or directionless.
  Scenario: Symmetric directional evidence keeps pair unresolved and blocks closure
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.00
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.25
    And pair-resolution minimum directional evidence count is 2
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.80 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS  |
      | H2:availability | 0.80 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_RIGHT","evidence_ids":["ref2"]}]                     | false              | SUPPORTS  |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "PAIR_RESOLUTION_UPDATED"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "pair_key" equals "H1|H2"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "verdict" equals "UNRESOLVED"
    And the audit log records event "DECISION_CONTRACT_FAILED"
    And audit events "DECISION_CONTRACT_FAILED" payload field "failing_conditions" include values:
      | value                        |
      | pairwise_coverage_below_min  |

  # Benefit: a clear directional verdict should count as resolved pair coverage
  # and contribute to decisive ranking between contenders.
  Scenario: Directional evidence resolves pair and enables decisive closure
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.00
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.10
    And pair-resolution minimum directional evidence count is 1
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment   |
      | H1:availability | 0.92 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS    |
      | H2:availability | 0.20 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                      | false              | CONTRADICTS |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H1"
    And the audit log records event "PAIR_RESOLUTION_UPDATED"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "pair_key" equals "H1|H2"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "verdict" equals "FAVORS_LEFT"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "strength" is at least 0.10
    And the audit log records event "DECISION_CONTRACT_PASSED"

  # Benefit: malformed typed discriminator payloads should not be able to
  # resolve pairs; they must remain unresolved and visible as such.
  Scenario: Invalid typed discriminator payload does not resolve pair
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.00
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.10
    And pair-resolution minimum directional evidence count is 1
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.85 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref_missing"]}]               | false              | SUPPORTS  |
      | H2:availability | 0.45 | 2 | 2 | 2 | 2 | ref2         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "DISCRIMINATOR_EVIDENCE_INVALID"
    And the audit log records event "PAIR_RESOLUTION_UPDATED"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "verdict" equals "UNRESOLVED"
    And the audit log records event "DECISION_CONTRACT_FAILED"
