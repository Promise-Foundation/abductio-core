# tests/bdd/features/25_one_shot_decision_contract_enforcement.feature
Feature: One-shot decision contract enforcement
  # This feature codifies a defensible one-shot contract:
  # no winner is emitted unless discriminatory adjudication is sufficiently
  # covered, contrasted, and stress-tested.

  # Benefit: prevents confident closure on a single favored story when the
  # strongest alternative has not been genuinely falsified.
  Scenario: Decision contract blocks winner when contrastive evidence is insufficient
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
      | id | statement              | exclusion_clause                |
      | H1 | Mechanism Alpha        | Not explained by any other root |
      | H2 | Mechanism Beta         | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                          |
      | H1     | H2     | Observable X favors H1 over H2         |
    And strict contrastive updates are required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.20
    And decision contract requires loser falsification evidence
    And decision contract requires counterevidence probe for winner
    And typed discriminator evidence is required
    And active discriminator coverage ratio is 0.20
    And minimum discriminator coverage ratio is 1.00
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | d1                | [{"id":"d1","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                        | false              | SUPPORTS  |
      | H2:availability | 0.60 | 2 | 2 | 2 | 2 | ref2         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "DECISION_CONTRACT_FAILED"
    And audit event "DECISION_CONTRACT_FAILED" payload includes:
      | field                            |
      | winner_root_id                   |
      | runner_up_root_id                |
      | failing_conditions               |
      | observed_pairwise_coverage_ratio |
      | min_pairwise_coverage_ratio      |

  # Benefit: allows decisive output when the winner survives a direct,
  # typed, contrastive challenge against the closest rival.
  Scenario: Decision contract passes when winner margin and adversarial checks are satisfied
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
      | id | statement              | exclusion_clause                |
      | H1 | Mechanism Alpha        | Not explained by any other root |
      | H2 | Mechanism Beta         | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                          |
      | H1     | H2     | Observable X favors H1 over H2         |
    And strict contrastive updates are required
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And decision contract minimum winner margin is 0.20
    And decision contract requires loser falsification evidence
    And decision contract requires counterevidence probe for winner
    And typed discriminator evidence is required
    And active discriminator coverage ratio is 1.00
    And minimum discriminator coverage ratio is 1.00
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment   |
      | H1:availability | 0.88 | 2 | 2 | 2 | 2 | ref1         | d1                | [{"id":"d1","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                        | false              | SUPPORTS    |
      | H2:availability | 0.20 | 2 | 2 | 2 | 2 | ref2         | d2                | [{"id":"d2","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]                        | false              | CONTRADICTS |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H1"
    And the audit log records event "DECISION_CONTRACT_PASSED"

  # Benefit: discriminator claims must be machine-auditable and evidence-linked;
  # untyped discriminator labels cannot inflate confidence.
  Scenario: Untyped discriminator evidence is rejected in strict typed mode
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
      | id | statement              | exclusion_clause                |
      | H1 | Mechanism Alpha        | Not explained by any other root |
      | H2 | Mechanism Beta         | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                          |
      | H1     | H2     | Observable X favors H1 over H2         |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value |
      | p                      | 0.90  |
      | A                      | 2     |
      | B                      | 2     |
      | C                      | 2     |
      | D                      | 2     |
      | evidence_ids           | (empty) |
      | discriminator_ids      | d1    |
      | discriminator_payloads | []    |
      | entailment             | SUPPORTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "DISCRIMINATOR_EVIDENCE_INVALID"
    And the audit log records policy warning "MISSING_ACTIVE_DISCRIMINATOR"

  # Benefit: confidence is calibrated by discriminatory coverage, preventing
  # high process confidence under sparse contrastive evidence.
  Scenario: Coverage-calibrated confidence cap binds root confidence
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
      | id | statement              | exclusion_clause                |
      | H1 | Mechanism Alpha        | Not explained by any other root |
      | H2 | Mechanism Beta         | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                          |
      | H1     | H2     | Observable X favors H1 over H2         |
    And active discriminator coverage ratio is 0.25
    And coverage-calibrated confidence cap is enabled
    And coverage confidence cap base is 0.40 and gain is 0.20
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key          | value |
      | p            | 0.90  |
      | A            | 2     |
      | B            | 2     |
      | C            | 2     |
      | D            | 2     |
      | evidence_ids | ref1  |
      | entailment   | SUPPORTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then root "H1" has k_root <= 0.45
    And the audit log records event "COVERAGE_CONFIDENCE_CAP_APPLIED"

  # Benefit: one-shot runs reserve budget for contrastive checks; if that
  # reservation is missed, the run reports underdetermination instead of closure.
  Scenario: Contrastive discriminator budget floor is enforced
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
      | id | statement              | exclusion_clause                |
      | H1 | Mechanism Alpha        | Not explained by any other root |
      | H2 | Mechanism Beta         | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                          |
      | H1     | H2     | Observable X favors H1 over H2         |
    And strict contrastive updates are required
    And decision contract is enabled
    And typed discriminator evidence is required
    And contrastive budget partition is enabled
    And minimum contrastive discriminator credits is 2
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.85 | 2 | 2 | 2 | 2 | ref1         | d1                | [{"id":"d1","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                        | false              | SUPPORTS  |
      | H2:availability | 0.45 | 2 | 2 | 2 | 2 | ref2         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "CONTRASTIVE_BUDGET_FLOOR_UNMET"
