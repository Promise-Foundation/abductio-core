# tests/bdd/features/26_contrastive_evaluator_contract.feature
Feature: Contrastive evaluator contract and context propagation
  # This feature hardens the evaluator interface so contrastive adjudication is
  # a first-class contract, not an optional prompt flourish.

  # Benefit: strict causal runs can only claim discriminative progress when
  # discriminator evidence is tied to an explicit root pair from context.
  Scenario: Evaluator emits discriminator evidence from contrastive context in strict mode
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
    And a scoped root "H1"
    And a deterministic evaluator that emits discriminator evidence from contrastive context
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And audit event "DISCRIMINATOR_EVIDENCE_RECORDED" payload includes:
      | field         |
      | typed_records |
    And the audit log does not record policy warning "MISSING_ACTIVE_DISCRIMINATOR"

  # Benefit: the evaluator schema remains domain-general; forecasting can use
  # the same typed fields with neutral/empty discriminators without false errors.
  Scenario: Forecasting mode accepts neutral typed outputs without strict contrastive penalty
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
      | H1 | Forecast is true | Not explained by any other root |
      | H2 | Forecast is false | Not explained by any other root |
    And domain profile "forecasting" is selected
    And a scoped root "H1"
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value   |
      | p                      | 0.58    |
      | A                      | 2       |
      | B                      | 1       |
      | C                      | 1       |
      | D                      | 1       |
      | evidence_ids           | ref1    |
      | discriminator_ids      | (empty) |
      | discriminator_payloads | []      |
      | entailment             | NEUTRAL |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log does not record event "DISCRIMINATOR_EVIDENCE_INVALID"
    And the audit log does not record policy warning "MISSING_ACTIVE_DISCRIMINATOR"

