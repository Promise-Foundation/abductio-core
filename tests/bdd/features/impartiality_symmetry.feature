@impartiality @abductio @fairness
Feature: Symmetric evaluation prevents focal privilege and framing bias
  As a diligence user
  I want all competing hypotheses to face the same obligations
  So that the system does not privilege one narrative by default

  Background:
    Given a promise scope with two competing roots "H_PASS" and "H_FAIL"
    And required obligation slots are configured uniformly for all roots
    And a fixed credit budget is configured

  Scenario: All roots are instantiated with the same required slots
    When I run evaluation
    Then the output should show the same slot names under "H_PASS" and "H_FAIL"
    And each root should have a score for every required slot

  Scenario: Reordering roots does not change results
    Given the same evidence and configuration
    When I run evaluation with roots listed in one order
    And I run evaluation with roots listed in the reverse order
    Then the credence vector should be identical
    And the anomalies should be identical

  Scenario: Evaluation is invariant to prompt framing when evidence is unchanged
    Given the same evidence and configuration
    When I run evaluation with framing text "assume it passes unless proven otherwise"
    And I run evaluation with framing text "assume it fails unless proven otherwise"
    Then the required slots evaluated should be identical
    And the credence vector should be identical

  Scenario: Weakest-slot explanation is reported for each root
    When I run evaluation
    Then each root should include a "weakest_slot" field
    And the "weakest_slot" should include the slot name and its confidence score
