# tests/bdd/features/45_pair_value_prioritized_adjudication.feature
Feature: Pair-adjudication value prioritization
  # This feature ranks unresolved pairs by elimination value so limited credits
  # reduce contender entropy faster.

  # Benefit: early credits are spent on pairs most likely to collapse the active set.
  Scenario: Queue selects highest elimination-value unresolved pair first
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
      | H3 | Mechanism Gamma | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pair-adjudication queue is enabled
    And pair-adjudication value prioritization is enabled
    And unresolved pair elimination-value estimates are:
      | root_a | root_b | value |
      | H1     | H2     | 0.92  |
      | H1     | H3     | 0.33  |
      | H2     | H3     | 0.27  |
    And credits 1
    When I run the engine for exactly 1 operation
    Then the audit log records event "PAIR_VALUE_PRIORITY_COMPUTED"
    And audit event "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "pair_key" equals "H1|H2"

  # Benefit: low-value comparisons are deferred when budget is insufficient.
  Scenario: Tight budget executes only high-value unresolved pair tasks
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
      | H3 | Mechanism Gamma | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pair-adjudication queue is enabled
    And pair-adjudication value prioritization is enabled
    And unresolved pair elimination-value estimates are:
      | root_a | root_b | value |
      | H1     | H2     | 0.90  |
      | H1     | H3     | 0.10  |
      | H2     | H3     | 0.08  |
    And pair-adjudication pair budget is 1
    And credits 2
    When I run the engine until credits exhausted
    Then audit events "PAIR_ADJUDICATION_TARGET_SELECTED" payload field "pair_key" do not include values:
      | value |
      | H1/H3 |
      | H2/H3 |
    And the audit log records event "PAIR_VALUE_DEFERRED_FOR_BUDGET"
