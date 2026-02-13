# tests/bdd/features/28_contender_space_semantics.feature
Feature: Contender-space semantics contract
  # This feature makes contender semantics explicit so the engine never runs
  # with an ambiguous hypothesis space.

  # Benefit: singleton-root investigations can run with a declared contract
  # instead of silently relying on implicit interpretation.
  Scenario: Singleton contender space is explicitly declared and accepted
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
    And contender space mode is "singleton_roots"
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids |
      | H1:availability | 0.70 | 2 | 2 | 2 | 2 | ref1         |
      | H2:availability | 0.30 | 2 | 2 | 2 | 2 | ref2         |
      | H3:availability | 0.20 | 2 | 2 | 2 | 2 | ref3         |
    And credits 3
    When I run the engine until credits exhausted
    Then the audit log records event "CONTENDER_SPACE_CHECKED"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "status" equals "PASSED"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "mode" equals "singleton_roots"

  # Benefit: compositional mode cannot be claimed without explicit story
  # composition metadata for each contender.
  Scenario: Compositional contender mode fails fast when story components are missing
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
    And contender space mode is "compositional_stories"
    And credits 5
    When I run the engine until credits exhausted
    Then stop_reason is "POLICY_CONFIG_INCOMPATIBLE"
    And no operations were executed
    And the audit log records event "CONTENDER_SPACE_CHECKED"
    And the audit log records event "CONTENDER_SPACE_INVALID"
    And the audit log records anomaly code "missing_story_components"

  # Benefit: compositional mode is accepted only when the run declares an
  # explicit causal-story basis, including multi-factor contenders.
  Scenario: Compositional contender mode is accepted with explicit story components
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
    And contender space mode is "compositional_stories"
    And contender story components are:
      | root_id | components      |
      | H1      | C_PUSHBACK      |
      | H2      | C_COMM,C_TRP    |
      | H3      | C_MECH          |
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids |
      | H1:availability | 0.65 | 2 | 2 | 2 | 2 | ref1         |
      | H2:availability | 0.55 | 2 | 2 | 2 | 2 | ref2         |
      | H3:availability | 0.10 | 2 | 2 | 2 | 2 | ref3         |
    And credits 3
    When I run the engine until credits exhausted
    Then the audit log records event "CONTENDER_SPACE_CHECKED"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "status" equals "PASSED"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "mode" equals "compositional_stories"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "multi_factor_story_count" equals "1"
