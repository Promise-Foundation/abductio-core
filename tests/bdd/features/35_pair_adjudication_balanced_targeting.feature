# tests/bdd/features/35_pair_adjudication_balanced_targeting.feature
Feature: Balanced pair-adjudication targeting
  # Benefit: unresolved-pair work must not repeatedly spend credits on only
  # one side of a pair. Early credits should cover both sides to reduce
  # one-sided winner lock-in and improve loser probing.
  Scenario: Pair queue alternates targets across both roots of a pair
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
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And a scoped root "H1"
    And a scoped root "H2"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
      | H2:availability | 0.80 | 2 | 2 | 2 | 2 | ref2         | (empty)           | []                                                                                                     | true               | SUPPORTS  |
    And credits 4
    When I run the engine for exactly 4 operations
    Then the audit log records at least 2 events "PAIR_ADJUDICATION_TARGET_SELECTED"
    And audit events "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "target_root_id" include values:
      | value |
      | H1    |
      | H2    |

  # Benefit: when one side is outside the current frontier, pair adjudication
  # still allocates work to that missing side instead of repeatedly spending
  # credits on the frontier-side root.
  Scenario: Missing pair side is bootstrapped into adjudication
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
    And the ledger is set to:
      | id    | p_ledger |
      | H1    | 0.85     |
      | H2    | 0.05     |
      | H_NOA | 0.05     |
      | H_UND | 0.05     |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And a scoped root "H1"
    And a scoped root "H2"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | (empty)           | []                     | true               | SUPPORTS  |
    And credits 2
    When I run the engine for exactly 2 operations
    Then the audit log records event "PAIR_ADJUDICATION_MISSING_SIDE_BOOTSTRAPPED"
    And audit events "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "target_root_id" include values:
      | value |
      | H2    |
