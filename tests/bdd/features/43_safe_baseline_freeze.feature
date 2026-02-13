# tests/bdd/features/43_safe_baseline_freeze.feature
Feature: Safe baseline freeze and replay contract
  # This feature prevents benchmark drift and forces attributable comparisons.

  # Benefit: every ablation comparison is anchored to a reproducible baseline.
  Scenario: Frozen baseline captures complete run identity
    Given a frozen benchmark baseline named "boeing_safe_v1"
    And frozen baseline model is "gpt-4.1-mini"
    And frozen baseline policy file is "case_studies/safe_baseline_v2.policy.json"
    And frozen baseline packet set includes:
      | case_id                              |
      | Boeing_737-8AS_9H-QAA_12-25          |
      | Short_Bros_SD3-60_N915GD_10-25       |
      | Spitfire_MK_26B_G-ENAA_01-26         |
    And frozen baseline random seeds are:
      | seed |
      | 11   |
      | 17   |
      | 23   |
    When I materialize the frozen baseline manifest
    Then the manifest includes fields:
      | field             |
      | baseline_id       |
      | model_id          |
      | policy_hash       |
      | packet_hash       |
      | seed_set_hash     |
      | prompt_bundle_hash|
    And the audit log records event "BASELINE_MANIFEST_FROZEN"

  # Benefit: no rerun can silently compare against a changed baseline.
  Scenario: Baseline drift blocks comparative benchmarking
    Given a frozen benchmark baseline named "boeing_safe_v1"
    And baseline drift is detected in field "policy_hash"
    When I start a comparative ablation run
    Then the run is rejected with reason "BASELINE_DRIFT_DETECTED"
    And the audit log records event "BASELINE_DRIFT_BLOCKED"

  # Benefit: replay determinism is explicit and testable for case studies.
  Scenario: Replay from frozen baseline is run-signature stable
    Given a frozen benchmark baseline named "boeing_safe_v1"
    And a completed run "run_A" tied to that baseline
    When I replay "run_A" from the frozen manifest
    Then replay output run signature equals original run signature
    And replay output top root distribution equals original top root distribution
    And the audit log records event "BASELINE_REPLAY_VERIFIED"
