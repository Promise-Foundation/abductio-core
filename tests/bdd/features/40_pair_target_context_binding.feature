# tests/bdd/features/40_pair_target_context_binding.feature
Feature: Pair-target context binding for adjudication tasks
  # Benefit: unresolved-pair queue credits must be spent on the selected pair,
  # not a different high-mass pair for the same root. This enforces pair-task
  # fidelity and prevents fake coverage progress.

  Scenario: Queue-selected pair overrides default primary pair in contrastive context
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
      | H1 | Alpha Mechanism | Not explained by any other root |
      | H2 | Zulu Mechanism  | Not explained by any other root |
      | H3 | Bravo Mechanism | Not explained by any other root |
    And the ledger is set to:
      | id    | p_ledger |
      | H1    | 0.05     |
      | H2    | 0.45     |
      | H3    | 0.35     |
      | H_NOA | 0.10     |
      | H_UND | 0.05     |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                       |
      | H1     | H2     | Observable X separates H1 from H2  |
      | H1     | H3     | Observable X separates H1 from H3  |
      | H2     | H3     | Observable X separates H2 from H3  |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 3
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And pair-adjudication pair budget is 3
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a deterministic evaluator that emits discriminator evidence from contrastive context
    And credits 1
    When I run the engine for exactly 1 operation
    Then audit event "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "pair_key" equals "H1|H2"
    And audit event "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "target_root_id" equals "H2"
    And the audit log records event "CONTRASTIVE_CONTEXT_TARGET_BOUND"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "target_pair_key" equals "H1|H2"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "default_primary_pair_key" equals "H2|H3"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "primary_pair_key" equals "H1|H2"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "target_pair_applied" equals "True"
    And the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
