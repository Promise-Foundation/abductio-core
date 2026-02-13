# tests/bdd/features/52_contender_retirement_and_typed_linker.feature
Feature: Contender retirement with directional typed evidence linking
  # This feature hardens two bottlenecks together:
  # 1) typed evidence must directionally link to pair discrimination without
  #    contradictory reuse, and
  # 2) decisively refuted contenders should retire so credits are not wasted.

  # Benefit: conflicting directional reuse of the same evidence cannot resolve
  # a pair; the run remains honestly underdetermined.
  Scenario: Directional typed evidence conflict blocks pair resolution
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
    And directional typed evidence linker is enabled
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.00
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.10
    And pair-resolution minimum directional evidence count is 2
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                | non_discriminative | entailment |
      | H1:availability | 0.88 | 2 | 2 | 2 | 2 | ref_shared   | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref_shared"]}]               | false              | SUPPORTS  |
      | H2:availability | 0.86 | 2 | 2 | 2 | 2 | ref_shared   | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_RIGHT","evidence_ids":["ref_shared"]}]              | false              | SUPPORTS  |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "TYPED_DIRECTIONAL_EVIDENCE_CONFLICT"
    And the audit log records event "DISCRIMINATOR_EVIDENCE_INVALID"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "verdict" equals "UNRESOLVED"

  # Benefit: when pair evidence decisively refutes contenders, they are retired
  # and removed from future pair scope so remaining credits focus on live rivals.
  Scenario: Decisively refuted contenders retire from adjudication scope
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
      | id | statement                      | exclusion_clause                |
      | H1 | Procedural deviation           | Not explained by any other root |
      | H2 | Communication breakdown        | Not explained by any other root |
      | H3 | Environment/marking deficiency | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                |
      | H1     | H2     | H1 facts separate from H2    |
      | H1     | H3     | H1 facts separate from H3    |
      | H2     | H3     | H2 facts separate from H3    |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And directional typed evidence linker is enabled
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.10
    And pair-resolution minimum directional evidence count is 1
    And contender retirement is enabled
    And contender retirement minimum decisive losses is 1
    And contender retirement minimum pair margin is 0.10
    And contender retirement minimum pair strength is 0.05
    And contender retirement requires no decisive wins
    And contender retirement mass floor is 0.01
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                                                                                                     | non_discriminative | entailment   |
      | H1:availability | 0.92 | 2 | 2 | 2 | 2 | ref_h1       | d12,d13           | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref_h1"]},{"id":"d13","pair":"H1/H3","direction":"FAVORS_LEFT","evidence_ids":["ref_h1"]}]                    | false              | SUPPORTS    |
      | H2:availability | 0.22 | 2 | 2 | 2 | 2 | ref_h2       | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref_h2"]}]                                                                                                      | false              | CONTRADICTS |
      | H3:availability | 0.24 | 2 | 2 | 2 | 2 | ref_h3       | d13               | [{"id":"d13","pair":"H1/H3","direction":"FAVORS_LEFT","evidence_ids":["ref_h3"]}]                                                                                                      | false              | CONTRADICTS |
    And credits 6
    When I run the engine until credits exhausted
    Then the top ledger root is "H1"
    And the audit log records event "CONTENDER_RETIRED"
    And audit events "CONTENDER_RETIRED" payload field "root_id" include values:
      | value |
      | H2    |
      | H3    |
    And the audit log records event "CONTENDER_RETIREMENT_PAIR_SCOPE_PRUNED"
