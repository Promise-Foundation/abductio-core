# tests/bdd/features/32_dynamic_abstention_mass.feature
Feature: Dynamic abstention mass replaces fixed H_UND floor
  # Benefit: abstention mass scales with actual unresolved discrimination
  # pressure, instead of forcing a static dominant floor.

  Scenario: Unresolved pair pressure increases H_UND without forcing 0.45
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
    And dynamic abstention mass is enabled
    And dynamic abstention unresolved-pair weight is 0.30
    And dynamic abstention contradiction-density weight is 0.00
    And dynamic abstention non-discriminative weight is 0.00
    And dynamic abstention mass minimum is 0.10
    And dynamic abstention mass maximum is 0.90
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                | value    |
      | p                  | 0.80     |
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
    Then root "H_UND" has p_ledger >= 0.39
    And root "H_UND" has p_ledger <= 0.44
    And the audit log records event "ABSTENTION_MASS_DYNAMIC_UPDATED"
    And audit event "ABSTENTION_MASS_DYNAMIC_UPDATED" payload field "applied" equals "True"

  # Benefit: contradiction-heavy runs can raise abstention even when pair
  # coverage exists, because conflict density itself is informative.
  Scenario: Contradiction density raises H_UND when valid contradictions accumulate
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
    And dynamic abstention mass is enabled
    And dynamic abstention unresolved-pair weight is 0.00
    And dynamic abstention contradiction-density weight is 0.40
    And dynamic abstention non-discriminative weight is 0.00
    And dynamic abstention mass minimum is 0.10
    And dynamic abstention mass maximum is 0.90
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                           |
      | p                      | 0.20                                                                            |
      | A                      | 2                                                                               |
      | B                      | 2                                                                               |
      | C                      | 2                                                                               |
      | D                      | 2                                                                               |
      | evidence_ids           | ref1                                                                            |
      | discriminator_ids      | d12                                                                             |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_RIGHT","evidence_ids":["ref1"]}] |
      | non_discriminative     | false                                                                           |
      | entailment             | CONTRADICTS                                                                     |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then root "H_UND" has p_ledger >= 0.49
    And the audit log records event "ABSTENTION_MASS_DYNAMIC_UPDATED"
    And audit event "ABSTENTION_MASS_DYNAMIC_UPDATED" payload field "contradiction_density" is at least 0.99

  # Benefit: when pairwise discrimination is resolved and contradictions are
  # sparse, abstention remains modest instead of snapping to a hard 0.45 floor.
  Scenario: Low pressure keeps H_UND below historical fixed floor
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
    And dynamic abstention mass is enabled
    And dynamic abstention unresolved-pair weight is 0.30
    And dynamic abstention contradiction-density weight is 0.30
    And dynamic abstention non-discriminative weight is 0.00
    And dynamic abstention mass minimum is 0.10
    And dynamic abstention mass maximum is 0.90
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                          |
      | p                      | 0.80                                                                           |
      | A                      | 2                                                                              |
      | B                      | 2                                                                              |
      | C                      | 2                                                                              |
      | D                      | 2                                                                              |
      | evidence_ids           | ref1                                                                           |
      | discriminator_ids      | d12                                                                            |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}] |
      | non_discriminative     | false                                                                          |
      | entailment             | SUPPORTS                                                                       |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then root "H_UND" has p_ledger <= 0.25
    And the audit log records event "ABSTENTION_MASS_DYNAMIC_UPDATED"
    And audit event "ABSTENTION_MASS_DYNAMIC_UPDATED" payload field "unresolved_pair_ratio" is at most 0.01
