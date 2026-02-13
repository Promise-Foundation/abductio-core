# tests/bdd/features/48_compositional_story_regularization.feature
Feature: Compositional story regularization and singleton equivalence
  # This feature treats every contender as a causal story, including singletons,
  # while regularizing larger compositions to avoid combinatorial overfit.

  # Benefit: singleton and composite contenders are represented in one coherent space.
  Scenario: Singleton roots are represented as cardinality-1 stories
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
    And contender space mode is "compositional_stories"
    And singleton stories are explicit contenders
    And compositional story auto-expansion is enabled
    And compositional story max cardinality is 2
    And credits 0
    When I run the engine until credits exhausted
    Then the session contains root "CS__H1"
    And the session contains root "CS__H2"
    And the session contains root "CS__H1__H2"
    And the audit log records event "COMPOSITIONAL_STORY_SPACE_BUILT"

  # Benefit: multi-factor outcomes can win when joint evidence is genuinely stronger.
  Scenario: Pair story outranks singleton roots when joint evidence is discriminative
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
      | id | statement           | exclusion_clause                |
      | H1 | Human-factor issue  | Not explained by any other root |
      | H2 | Procedural weakness | Not explained by any other root |
    And contender space mode is "compositional_stories"
    And singleton stories are explicit contenders
    And compositional story auto-expansion is enabled
    And compositional story max cardinality is 2
    And compositional regularization is enabled
    And compositional complexity penalty lambda is 0.08
    And joint-support evidence for story "CS__H1__H2" is 0.90
    And joint-support evidence for story "CS__H1" is 0.58
    And joint-support evidence for story "CS__H2" is 0.55
    And credits 2
    When I run the engine until credits exhausted
    Then the top ledger root is "CS__H1__H2"
    And the audit log records event "COMPOSITIONAL_STORY_SCORED"

  # Benefit: unsupported composites are penalized instead of crowding out simpler stories.
  Scenario: Complexity penalty blocks unsupported composite winner
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
      | id | statement           | exclusion_clause                |
      | H1 | Human-factor issue  | Not explained by any other root |
      | H2 | Procedural weakness | Not explained by any other root |
    And contender space mode is "compositional_stories"
    And singleton stories are explicit contenders
    And compositional story auto-expansion is enabled
    And compositional story max cardinality is 2
    And compositional regularization is enabled
    And compositional complexity penalty lambda is 0.15
    And joint-support evidence for story "CS__H1__H2" is 0.51
    And joint-support evidence for story "CS__H1" is 0.57
    And credits 2
    When I run the engine until credits exhausted
    Then the top ledger root is "CS__H1"
    And the audit log records event "COMPOSITIONAL_STORY_REGULARIZATION_APPLIED"
