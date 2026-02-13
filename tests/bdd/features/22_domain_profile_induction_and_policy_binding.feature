# tests/bdd/features/22_domain_profile_induction_and_policy_binding.feature
Feature: Domain profile induction and policy binding
  # This feature defines how ABDUCTIO should enter previously unseen domains
  # without requiring code changes per domain.

  # Benefit: the engine emits an explicit induced profile and binds policy
  # declaratively, so behavior is auditable rather than hidden in prompts.
  Scenario: Unseen domain triggers declarative profile induction
    Given default config:
      | tau        | 0.70 |
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
    And a hypothesis set with named roots:
      | id | statement                        | exclusion_clause                |
      | H1 | Causal chain A explains outcome | Not explained by any other root |
      | H2 | Causal chain B explains outcome | Not explained by any other root |
    And domain profile auto-selection is enabled
    And domain induction minimum confidence is 0.70
    And this case is marked as unseen domain "industrial_incident_v1"
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with at least one evaluation outcome
    And credits 4
    When I run the engine until it stops
    Then the audit log records event "DOMAIN_PROFILE_INDUCED"
    And audit event "DOMAIN_PROFILE_INDUCED" payload includes:
      | field              |
      | domain_id          |
      | profile_name       |
      | profile_confidence |
    And the audit log records event "PROFILE_POLICY_APPLIED"
    And session metadata includes induced profile fields:
      | field                     |
      | reasoning_profile         |
      | reasoning_mode            |
      | profile_source            |
      | strict_contrastive_policy |

  # Benefit: if profile induction is uncertain, the engine degrades safely
  # instead of applying an overconfident domain policy.
  Scenario: Low-confidence induction falls back to cautious exploration
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
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Will a new synthetic fuel policy reduce emissions next year"
    And domain profile auto-selection is enabled
    And domain induction minimum confidence is 0.70
    And induced profile confidence for this case is 0.40
    And a deterministic decomposer that will scope all roots
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.62 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.58 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.55 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.52 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.50 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.49 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then stop_reason is "EPISTEMICALLY_EXHAUSTED"
    And the audit log records event "DOMAIN_INDUCTION_LOW_CONFIDENCE"
    And the simplified metadata includes at least 1 next-step recommendation

  # Benefit: forecasting and causal investigation can share one framework while
  # using different profile policies, avoiding domain-specific code forks.
  Scenario: Profile routing keeps forecasting flexible and causal mode strict
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
    And domain profile "forecasting" is selected
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.80 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.78 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.76 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.45 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.44 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.42 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then the audit log records event "PROFILE_POLICY_APPLIED"
    And audit event "PROFILE_POLICY_APPLIED" payload includes:
      | field                               |
      | profile_name                        |
      | strict_contrastive_updates_required |
      | min_decomposition_depth_per_slot    |

