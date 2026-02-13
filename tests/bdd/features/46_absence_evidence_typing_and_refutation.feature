# tests/bdd/features/46_absence_evidence_typing_and_refutation.feature
Feature: Typed absence evidence for contrastive refutation
  # This feature allows defensible use of "expected signal absent" evidence in
  # pair discrimination without accepting untyped absence claims.

  # Benefit: human-factor and procedural cases can refute alternatives using
  # explicit negative checks, not only positive smoking-gun facts.
  Scenario: Typed absence evidence resolves a pair directionally
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
      | id | statement                         | exclusion_clause                |
      | H1 | Procedural deviation caused event | Not explained by any other root |
      | H2 | Mechanical failure caused event   | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                         |
      | H1     | H2     | No-mechanical-signature favors H1     |
    And typed discriminator evidence is required
    And typed absence evidence is enabled
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.10
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids     | discriminator_ids | discriminator_payloads                                                                                                                                      | non_discriminative | entailment   |
      | H1:availability | 0.88 | 2 | 2 | 2 | 2 | inspect_ref      | d_abs             | [{"id":"d_abs","pair":"H1/H2","direction":"FAVORS_LEFT","kind":"ABSENCE","claim":"expected mechanical fault signature absent","evidence_ids":["inspect_ref"]}] | false              | SUPPORTS    |
      | H2:availability | 0.28 | 2 | 2 | 2 | 2 | inspect_ref      | d_abs             | [{"id":"d_abs","pair":"H1/H2","direction":"FAVORS_LEFT","kind":"ABSENCE","claim":"expected mechanical fault signature absent","evidence_ids":["inspect_ref"]}] | false              | CONTRADICTS |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H1"
    And the audit log records event "ABSENCE_EVIDENCE_TYPED_ACCEPTED"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "verdict" equals "FAVORS_LEFT"

  # Benefit: untyped absence claims cannot be used as hidden refutation.
  Scenario: Untyped absence claim is rejected and pair remains unresolved
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
      | id | statement                         | exclusion_clause                |
      | H1 | Procedural deviation caused event | Not explained by any other root |
      | H2 | Mechanical failure caused event   | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                         |
      | H1     | H2     | No-mechanical-signature favors H1     |
    And typed discriminator evidence is required
    And typed absence evidence is enabled
    And pair-resolution adjudication engine is enabled
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.88 | 2 | 2 | 2 | 2 | inspect_ref  | d_abs             | [{"id":"d_abs","pair":"H1/H2","direction":"FAVORS_LEFT","claim":"no mechanical signs observed"}]      | false              | SUPPORTS  |
      | H2:availability | 0.40 | 2 | 2 | 2 | 2 | inspect_ref  | (empty)           | []                                                                                                                     | true               | SUPPORTS  |
    And credits 3
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "ABSENCE_EVIDENCE_UNTYPED_REJECTED"
    And audit event "PAIR_RESOLUTION_UPDATED" payload field "verdict" equals "UNRESOLVED"
