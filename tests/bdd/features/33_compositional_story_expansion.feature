# tests/bdd/features/33_compositional_story_expansion.feature
Feature: Compositional contender expansion (cardinality-limited)
  # Benefit: the contender set can represent multi-factor causal stories,
  # not only singleton roots.

  Scenario: Auto-expansion adds pair stories when max cardinality is 2
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
    And compositional story auto-expansion is enabled
    And compositional story max cardinality is 2
    And credits 0
    When I run the engine until credits exhausted
    Then the session contains root "CS__H1__H2"
    And the session contains root "CS__H1__H3"
    And the session contains root "CS__H2__H3"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "status" equals "PASSED"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "root_count" equals "6"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "max_story_cardinality" equals "2"

  # Benefit: cardinality limits prevent combinatorial explosion by design.
  Scenario: Cardinality cap blocks larger composite stories
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
    And compositional story auto-expansion is enabled
    And compositional story max cardinality is 2
    And credits 0
    When I run the engine until credits exhausted
    Then the session does not contain root "CS__H1__H2__H3"
    And audit event "CONTENDER_SPACE_CHECKED" payload field "root_count" equals "6"
