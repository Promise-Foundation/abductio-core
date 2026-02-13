# tests/bdd/features/47_domain_calibrated_inference_weighting.feature
Feature: Domain-calibrated inference weighting
  # This feature calibrates inference leverage by domain and source quality,
  # so human-factor evidence is neither ignored nor over-trusted.

  # Benefit: direct participant admissions in aviation investigation carry
  # appropriately strong inferential weight.
  Scenario: Aviation human-factors profile boosts credible participant inference
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
      | id | statement                              | exclusion_clause                |
      | H1 | Instructor distraction caused overshoot | Not explained by any other root |
      | H2 | Mechanical issue caused overshoot       | Not explained by any other root |
    And reasoning profile is "aviation_human_factors"
    And inference weighting calibration is enabled
    And profile inference multipliers are:
      | source_type             | multiplier |
      | participant_admission   | 0.85       |
      | third_party_observation | 0.70       |
      | generic_inference       | 0.60       |
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | evidence_types               | entailment |
      | H1:availability | 0.86 | 2 | 2 | 2 | 2 | crew_ref     | participant_admission        | SUPPORTS  |
      | H2:availability | 0.35 | 2 | 2 | 2 | 2 | inspect_ref  | direct_fact                  | CONTRADICTS |
    And credits 4
    When I run the engine until credits exhausted
    Then root "H1" has p_ledger >= 0.45
    And the audit log records event "INFERENCE_WEIGHT_PROFILE_APPLIED"
    And audit event "INFERENCE_WEIGHT_PROFILE_APPLIED" payload field "profile_name" equals "aviation_human_factors"

  # Benefit: weaker profiles stay conservative even when claims are inferential.
  Scenario: Generic profile keeps conservative inference leverage
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
      | id | statement                              | exclusion_clause                |
      | H1 | Instructor distraction caused overshoot | Not explained by any other root |
      | H2 | Mechanical issue caused overshoot       | Not explained by any other root |
    And reasoning profile is "generic_causal"
    And inference weighting calibration is enabled
    And profile inference multipliers are:
      | source_type             | multiplier |
      | participant_admission   | 0.60       |
      | third_party_observation | 0.60       |
      | generic_inference       | 0.60       |
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | evidence_types               | entailment |
      | H1:availability | 0.86 | 2 | 2 | 2 | 2 | crew_ref     | participant_admission        | SUPPORTS  |
      | H2:availability | 0.35 | 2 | 2 | 2 | 2 | inspect_ref  | direct_fact                  | CONTRADICTS |
    And credits 4
    When I run the engine until credits exhausted
    Then root "H_UND" has p_ledger >= 0.20
    And the audit log records event "INFERENCE_WEIGHT_PROFILE_APPLIED"
    And audit event "INFERENCE_WEIGHT_PROFILE_APPLIED" payload field "profile_name" equals "generic_causal"
