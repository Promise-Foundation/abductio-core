# tests/bdd/features/15_contrastive_reasoning_conformance.feature
Feature: Contrastive reasoning conformance
  Strict mode must bound non-discriminative updates, enforce contradiction
  penalties, and elevate principled abstention when evidence does not
  adjudicate competitors.

  Background:
    Given default config:
      | tau        | 0.90 |
      | epsilon    | 0.05 |
      | gamma      | 0.20 |
      | alpha      | 0.40 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key     | role |
      | availability | NEC  |

  Scenario: Strict mode bounds non-discriminative drift per evaluation
    Given a hypothesis set with named roots:
      | id | statement       | exclusion_clause                |
      | H1 | Mechanism Alpha | Not explained by any other root |
      | H2 | Mechanism Beta  | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                       |
      | H1     | H2     | Observable X separates H1 from H2  |
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key               | value   |
      | p                 | 0.90    |
      | A                 | 2       |
      | B                 | 2       |
      | C                 | 2       |
      | D                 | 2       |
      | evidence_ids      | ref1    |
      | discriminator_ids | (empty) |
      | non_discriminative| true    |
      | entailment        | SUPPORTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records bounded non-discriminative drift for root "H1" slot "availability" with epsilon 0.02

  Scenario: Contradiction evidence enforces a minimum negative penalty
    Given a hypothesis set with named roots:
      | id | statement       | exclusion_clause                |
      | H1 | Mechanism Alpha | Not explained by any other root |
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.90
    And a deterministic evaluator that returns for node "H1:availability":
      | key               | value       |
      | p                 | 0.80        |
      | A                 | 2           |
      | B                 | 2           |
      | C                 | 2           |
      | D                 | 2           |
      | evidence_ids      | ref1        |
      | entailment        | CONTRADICTS |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records contradiction penalty for root "H1" slot "availability" with floor 0.25

  Scenario: Strict unresolved updates elevate H_UND over named roots
    Given a hypothesis set with named roots:
      | id | statement       | exclusion_clause                |
      | H1 | Mechanism Alpha | Not explained by any other root |
      | H2 | Mechanism Beta  | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                       |
      | H1     | H2     | Observable X separates H1 from H2  |
    And a scoped root "H1"
    And a scoped root "H2"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | non_discriminative | entailment |
      | H1:availability | 0.50 | 2 | 2 | 2 | 2 | ref1         | (empty)           | true               | SUPPORTS  |
      | H2:availability | 0.50 | 2 | 2 | 2 | 2 | ref2         | (empty)           | true               | SUPPORTS  |
    And credits 2
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
