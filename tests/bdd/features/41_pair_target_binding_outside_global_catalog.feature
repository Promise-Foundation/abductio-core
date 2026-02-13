# tests/bdd/features/41_pair_target_binding_outside_global_catalog.feature
Feature: Pair-target binding survives global pair pruning
  # Benefit: when pair-queue selects an active-set pair that is no longer in the
  # globally budget-pruned pair catalog, the selected pair is still injected and
  # evaluated. This preserves queue-task fidelity under budget pruning.

  Scenario: Active-set selected pair is applied even when absent from global candidates
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
      | H1    | 0.305    |
      | H2    | 0.31     |
      | H3    | 0.335    |
      | H_NOA | 0.03     |
      | H_UND | 0.02     |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                      |
      | H1     | H2     | Observable A separates H1 from H2 |
      | H1     | H3     | Observable B separates H1 from H3 |
      | H2     | H3     | Observable C separates H2 from H3 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And pair-adjudication pair budget is 1
    And pair-adjudication active-set lock is disabled
    And a scoped root "H1"
    And a scoped root "H2"
    And a scoped root "H3"
    And a deterministic evaluator that emits discriminator evidence from contrastive context
    And a deterministic evaluator that returns for node "H2:availability":
      | p            | 0.0    |
      | A            | 2      |
      | B            | 2      |
      | C            | 2      |
      | D            | 2      |
      | evidence_ids | ref_h2 |
      | entailment   | SUPPORTS |
    And credits 2
    When I run the engine for exactly 2 operations
    Then audit event "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "pair_key" equals "H1|H3"
    And audit event "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "target_root_id" equals "H1"
    And the audit log records event "CONTRASTIVE_CONTEXT_TARGET_BOUND"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "target_pair_key" equals "H1|H3"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "primary_pair_key" equals "H1|H3"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "target_pair_applied" equals "True"
    And audit event "CONTRASTIVE_CONTEXT_TARGET_BOUND" payload field "candidate_pair_count" equals "1"
    And the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
