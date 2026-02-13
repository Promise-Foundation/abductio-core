# tests/bdd/features/23_contrastive_adjudication_and_und_certification.feature
Feature: Contrastive adjudication and underdetermination certification
  # This feature prevents H_UND from becoming a default sink and requires
  # explicit contrastive adjudication attempts before abstention is certified.

  # Benefit: unresolved alternatives are surfaced explicitly as a problem to
  # solve, not silently converted into a final verdict.
  Scenario: Incomplete pairwise adjudication blocks decisive closure
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
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
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
    And active discriminator coverage ratio is 0.20
    And minimum discriminator coverage ratio is 1.00
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key | p    | A | B | C | D | evidence_ids | discriminator_ids | non_discriminative | entailment |
      | H1:availability | 0.70 | 2 | 2 | 2 | 2 | ref1 | (empty) | true | SUPPORTS |
      | H2:availability | 0.70 | 2 | 2 | 2 | 2 | ref2 | (empty) | true | SUPPORTS |
    And credits 8
    When I run the engine until it stops
    Then stop_reason is "EPISTEMICALLY_EXHAUSTED"
    And the audit log records event "PAIRWISE_ADJUDICATION_INCOMPLETE"
    And the audit log records event "NEXT_STEPS_GENERATED"
    And next-step guidance lists unresolved root pair "H1|H2"

  # Benefit: once adjudication attempts are complete and still symmetric, H_UND
  # is allowed as an explicit, justified conclusion rather than a fallback.
  Scenario: Certified underdetermination is allowed after completed adjudication attempts
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
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
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
    And active discriminator coverage ratio is 1.00
    And minimum discriminator coverage ratio is 1.00
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key | p    | A | B | C | D | evidence_ids | discriminator_ids | non_discriminative | entailment |
      | H1:availability | 0.50 | 2 | 2 | 2 | 2 | ref1 | d1 | false | SUPPORTS |
      | H2:availability | 0.50 | 2 | 2 | 2 | 2 | ref2 | d1 | false | SUPPORTS |
      | H1:fit_to_key_features | 0.50 | 2 | 2 | 2 | 2 | ref3 | d2 | false | SUPPORTS |
      | H2:fit_to_key_features | 0.50 | 2 | 2 | 2 | 2 | ref4 | d2 | false | SUPPORTS |
    And credits 10
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "UNDERDETERMINATION_CERTIFIED"
    And audit event "UNDERDETERMINATION_CERTIFIED" payload includes:
      | field                      |
      | pairwise_coverage_ratio    |
      | unresolved_pairs_count     |
      | discriminative_updates     |
      | non_discriminative_updates |

  # Benefit: this locks in the conservative contrastive behavior so supportive
  # but non-discriminative evidence cannot create fake certainty.
  Scenario: Non-discriminative support remains bounded under strict mode
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
      | discriminator_ids  | (empty)  |
      | non_discriminative | true     |
      | entailment         | SUPPORTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records bounded non-discriminative drift for root "H1" slot "availability" with epsilon 0.02

