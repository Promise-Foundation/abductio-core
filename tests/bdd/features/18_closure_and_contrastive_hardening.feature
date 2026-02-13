# tests/bdd/features/18_closure_and_contrastive_hardening.feature
Feature: Closure and contrastive hardening
  # This feature tightens stopping and contrastive logic so the engine
  # cannot close early on shallow agreement and must demonstrate explicit
  # discrimination among competitors.

  # Benefit: prevents premature termination when confidence is high only in a
  # shallow tree; requires depth + winner margin before closure.
  Scenario: Frontier confidence requires margin and minimum decomposition depth
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
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And minimum winner margin for closure is 0.10
    And minimum decomposition depth per NEC slot is 1
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.56 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.54 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.55 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.53 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.52 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.51 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then stop_reason is "CLOSURE_GATES_UNMET"
    And each root has minimum decomposition depth 1 for all required NEC slots
    And the audit log records event "FRONTIER_CONFIDENCE_DEFERRED"

  # Benefit: high positive updates must be contrastive; generic support
  # without discriminator evidence cannot produce large belief shifts.
  Scenario: Non-discriminative support is bounded in strict contrastive mode
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
    And the audit log records policy warning "MISSING_ACTIVE_DISCRIMINATOR"

  # Benefit: unresolved contradiction/discriminator gaps become explicit
  # underdetermination pressure instead of silent confidence inflation.
  Scenario: Uncertainty tax moves mass to H_UND when contradiction resolution is incomplete
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
    And unresolved contradiction pressure is 0.70
    And active discriminator coverage ratio is 0.20
    And minimum discriminator coverage ratio is 0.60
    And a scoped root "H1"
    And a scoped root "H2"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | non_discriminative | entailment   |
      | H1:availability | 0.55 | 2 | 2 | 2 | 2 | ref1         | (empty)           | true               | CONTRADICTS |
      | H2:availability | 0.55 | 2 | 2 | 2 | 2 | ref2         | (empty)           | true               | CONTRADICTS |
    And credits 2
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And root "H_UND" has p_ledger >= 0.30
    And the audit log records event "UNCERTAINTY_TAX_APPLIED"

