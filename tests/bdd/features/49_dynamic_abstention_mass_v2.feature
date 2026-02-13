# tests/bdd/features/49_dynamic_abstention_mass_v2.feature
Feature: Dynamic abstention mass v2 without fixed dominant floor
  # This feature replaces hard-floor underdetermination behavior with a pressure
  # model that responds to unresolved pairs, contradiction density, and frame quality.

  # Benefit: underdetermination can be low when the case is well resolved.
  Scenario: Low unresolved pressure allows H_UND below historical fixed floor
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
    And dynamic abstention mass is enabled
    And dynamic abstention v2 is enabled
    And fixed abstention dominant floor is disabled
    And dynamic abstention unresolved-pair weight is 0.35
    And dynamic abstention contradiction-density weight is 0.35
    And dynamic abstention frame-adequacy weight is 0.30
    And pair-resolution adjudication engine is enabled
    And pair-resolution minimum directional margin is 0.10
    And a scoped root "H1"
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                          |
      | p                      | 0.90                                                                           |
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
    Then root "H_UND" has p_ledger <= 0.20
    And the audit log records event "ABSTENTION_MASS_V2_UPDATED"

  # Benefit: underdetermination still increases when unresolved pressure is high.
  Scenario: High unresolved and contradiction pressure increases H_UND
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
      | H3 | Mechanism Gamma | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And dynamic abstention mass is enabled
    And dynamic abstention v2 is enabled
    And fixed abstention dominant floor is disabled
    And dynamic abstention unresolved-pair weight is 0.40
    And dynamic abstention contradiction-density weight is 0.40
    And dynamic abstention frame-adequacy weight is 0.20
    And a scoped root "H1"
    And a deterministic evaluator that returns for node "H1:availability":
      | key                | value      |
      | p                  | 0.30       |
      | A                  | 2          |
      | B                  | 2          |
      | C                  | 2          |
      | D                  | 2          |
      | evidence_ids       | ref1       |
      | discriminator_ids  | (empty)    |
      | non_discriminative | true       |
      | entailment         | CONTRADICTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then root "H_UND" has p_ledger >= 0.50
    And the audit log records event "ABSTENTION_MASS_V2_UPDATED"
