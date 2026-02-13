# tests/bdd/features/31_pair_adjudication_queue.feature
Feature: Pair adjudication queue scheduling
  # This feature ensures unresolved contender pairs are treated as explicit work
  # items, not just closure checks.

  # Benefit: credits are directed to unresolved contrastive pairs in the active
  # contender set, improving adjudication completeness before abstention.
  Scenario: Scheduler resolves active-set pair queue before default scheduling
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                      |
      | H1     | H2     | Observable X separates H1 from H2 |
      | H1     | H3     | Observable X separates H1 from H3 |
      | H2     | H3     | Observable X separates H2 from H3 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS  |
      | H2:availability | 0.80 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                      | false              | SUPPORTS  |
      | H3:availability | 0.70 | 2 | 2 | 2 | 2 | ref3         | d13               | [{"id":"d13","pair":"H1/H3","direction":"FAVORS_LEFT","evidence_ids":["ref3"]}]                      | false              | SUPPORTS  |
    And credits 2
    When I run the engine for exactly 2 operations
    Then the audit log records event "PAIR_ADJUDICATION_QUEUE_UPDATED"
    And the audit log records event "PAIR_ADJUDICATION_TARGET_SELECTED"
    And audit event "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "pair_key" equals "H1|H2"
    And audit event "PAIR_ADJUDICATION_QUEUE_UPDATED" payload field "status" equals "COMPLETE"
