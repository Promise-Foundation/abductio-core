# tests/bdd/features/29_contrastive_evidence_typing_contract.feature
Feature: Contrastive evidence typing contract
  # This feature enforces explicit evidence typing in strict contrastive mode:
  # evidence must be declared discriminative or shared/non-discriminative
  # before it may influence winner-vs-runner-up margins.

  # Benefit: prevents untyped supportive evidence from silently creating
  # contrastive movement in strict certification runs.
  Scenario: Untyped evidence is blocked from moving margins in strict mode
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And evidence discrimination tags are required
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                | value    |
      | p                  | 0.90     |
      | A                  | 2        |
      | B                  | 2        |
      | C                  | 2        |
      | D                  | 2        |
      | evidence_ids       | ref1     |
      | non_discriminative | false    |
      | entailment         | SUPPORTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "UNTYPED_EVIDENCE_BLOCKED"
    And the audit log records policy warning "MISSING_EVIDENCE_DISCRIMINATION_TAGS"
    And the audit log records delta_w = 0.0 within 0.000001

  # Benefit: shared evidence can still be logged and processed, but any
  # resulting drift is explicitly bounded by policy.
  Scenario: Explicit non-discriminative evidence receives only bounded drift
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And evidence discrimination tags are required
    And strict non-discriminative margin epsilon is 0.01
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                | value    |
      | p                  | 0.90     |
      | A                  | 2        |
      | B                  | 2        |
      | C                  | 2        |
      | D                  | 2        |
      | evidence_ids       | ref1     |
      | non_discriminative | true     |
      | entailment         | SUPPORTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log does not record event "UNTYPED_EVIDENCE_BLOCKED"
    And audit event "NON_DISCRIMINATIVE_EVAL_TAGGED" payload field "epsilon_nc" equals "0.01"
    And the audit log records bounded non-discriminative drift for root "H1" slot "availability" with epsilon 0.01

  # Benefit: typed discriminative evidence remains fully admissible under the
  # stricter typing contract.
  Scenario: Typed discriminative evidence is admitted under strict typing contract
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
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And evidence discrimination tags are required
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                                               |
      | p                      | 0.90                                                                                                |
      | A                      | 2                                                                                                   |
      | B                      | 2                                                                                                   |
      | C                      | 2                                                                                                   |
      | D                      | 2                                                                                                   |
      | evidence_ids           | ref1                                                                                                |
      | discriminator_ids      | d12                                                                                                 |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                   |
      | non_discriminative     | false                                                                                               |
      | entailment             | SUPPORTS                                                                                            |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And the audit log does not record event "UNTYPED_EVIDENCE_BLOCKED"
    And the audit log does not record policy warning "MISSING_EVIDENCE_DISCRIMINATION_TAGS"
