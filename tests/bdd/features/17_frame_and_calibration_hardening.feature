# tests/bdd/features/17_frame_and_calibration_hardening.feature
Feature: Frame adequacy and calibration hardening
  # This feature hardens confidence semantics without replacing ABDUCTIO's core:
  # same decomposition/evaluation ledger mechanics, but stricter treatment of
  # frame quality, confidence interpretation, and forecasting calibration.

  # Benefit: prevents "confidently wrong frame" outcomes where internals look
  # clean but the hypothesis frame is a poor fit for the actual evidence regime.
  Scenario: Weak frame adequacy caps confidence and reserves abstention mass
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And frame adequacy score is 0.30
    And minimum acceptable frame adequacy is 0.60
    And frame inadequacy caps root confidence at 0.55
    And frame inadequacy reserves at least 0.25 ledger mass for "H_UND"
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.85 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.82 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.80 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.30 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.35 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.40 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then root "H_YES" has k_root <= 0.55
    And root "H_NO" has k_root <= 0.55
    And root "H_UND" has p_ledger >= 0.25
    And the audit log records anomaly code "FRAME_INADEQUATE"

  # Benefit: distinguishes "confidence in process quality" from "confidence in
  # empirical truth-tracking", preventing UI overstatement.
  Scenario: Displayed confidence uses the minimum of process and calibrated confidence
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And calibration profile "forecasting_v1" reports calibrated confidence 0.45 for this claim class
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
    Then the simplified metadata records process confidence 0.90
    And the simplified metadata records calibrated confidence 0.45
    And the simplified opinion confidence is 0.45
    And the audit log records event "CONFIDENCE_PROJECTED_CONSERVATIVELY"

  # Benefit: forecasting claims cannot jump to very high confidence without
  # validated historical calibration, reducing domain-specific overconfidence.
  Scenario: Forecasting profile applies a hard confidence cap when calibration is unvalidated
    Given required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |
    And a simplified claim "Is the UK economy going to grow next year"
    And a deterministic decomposer that will scope all roots
    And reasoning profile is "forecasting"
    And historical calibration status is "unvalidated"
    And forecasting confidence hard cap is 0.55
    And a deterministic evaluator with the following outcomes:
      | node_key                  | p    | A | B | C | D | evidence_ids |
      | H_YES:availability        | 0.84 | 2 | 2 | 2 | 2 | ref1         |
      | H_YES:fit_to_key_features | 0.80 | 2 | 2 | 2 | 2 | ref2         |
      | H_YES:defeater_resistance | 0.77 | 2 | 2 | 2 | 2 | ref3         |
      | H_NO:availability         | 0.35 | 2 | 2 | 2 | 2 | ref4         |
      | H_NO:fit_to_key_features  | 0.33 | 2 | 2 | 2 | 2 | ref5         |
      | H_NO:defeater_resistance  | 0.31 | 2 | 2 | 2 | 2 | ref6         |
    And credits 12
    When I run the simplified claim interface until it stops
    Then root "H_YES" has k_root <= 0.55
    And the simplified opinion confidence is 0.55
    And the audit log records event "FORECAST_CALIBRATION_CAP_APPLIED"

