# tests/bdd/features/50_dual_output_selection_and_certification.feature
Feature: Dual output contract for selection and certification
  # This feature separates forced-choice ranking from high-bar certification so
  # decisiveness and safety are both measured without conflation.

  # Benefit: users always get a best-current explanation even when certification abstains.
  Scenario: Selection returns a leader while certification abstains
    Given default config:
      | tau        | 0.80 |
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
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And dual outputs are enabled
    And selection output is always required
    And certification output allows abstention
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads | non_discriminative | entailment |
      | H1:availability | 0.84 | 2 | 2 | 2 | 2 | ref1         | (empty)           | []                     | true               | SUPPORTS  |
      | H2:availability | 0.60 | 2 | 2 | 2 | 2 | ref2         | (empty)           | []                     | true               | SUPPORTS  |
    And credits 3
    When I run the engine until credits exhausted
    Then selection output top root is "H1"
    And certification output status is "ABSTAIN"
    And certification output top root is "H_UND"
    And the audit log records event "DUAL_OUTPUTS_EMITTED"

  # Benefit: when certification conditions are met, both outputs converge.
  Scenario: Selection and certification agree when pair coverage passes
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
    And typed discriminator evidence is required
    And pair-resolution adjudication engine is enabled
    And dual outputs are enabled
    And decision contract is enabled
    And decision contract minimum pairwise coverage ratio is 1.00
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment   |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]      | false              | SUPPORTS    |
      | H2:availability | 0.20 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref2"]}]      | false              | CONTRADICTS |
    And credits 4
    When I run the engine until credits exhausted
    Then selection output top root is "H1"
    And certification output status is "CERTIFIED"
    And certification output top root is "H1"
    And the audit log records event "DECISION_CONTRACT_PASSED"
