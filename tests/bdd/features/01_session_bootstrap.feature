# tests/bdd/features/01_session_bootstrap.feature
Feature: Session bootstrap and MECE initialization
  ABDUCTIO MVP must initialize a session deterministically and maintain a MECE ledger
  with an explicit H_other absorber.

  Background:
    Given default config:
      | tau     | 0.70 |
      | epsilon | 0.05 |
      | gamma   | 0.20 |
      | alpha   | 0.40 |
      | beta    | 1.00 |
      | W       | 3.00 |
      | lambda_voi | 0.10 |

  Scenario: Initialize with explicit roots and H_other is always present
    Given a hypothesis set with named roots:
      | id   | statement                               | exclusion_clause                     |
      | H1   | NHI encounter at Ariel School            | Not explained by any other root      |
      | H2   | Psychological priming + contagion         | Not explained by any other root      |
      | H3   | Misinterpretation of mundane stimuli      | Not explained by any other root      |
      | H4   | Coordinated hoax by humans                | Not explained by any other root      |
    And credits 5
    When I start a session for scope "Ariel School incident"
    Then the session contains root "H_other"
    And the ledger probabilities sum to 1.0 within 1e-9
    And each named root has p_ledger = (1 - gamma) / N where N is count(named_roots)
    And H_other has p_ledger = gamma
    And every root starts with k_root = 0.15
    And every named root starts with status "UNSCOPED"

  Scenario: Canonical IDs are stable and independent of input order
    Given a hypothesis set with named roots:
      | id   | statement                  | exclusion_clause                |
      | H1   | Alpha mechanism            | Not explained by any other root |
      | H2   | Beta mechanism             | Not explained by any other root |
      | H3   | Gamma mechanism            | Not explained by any other root |
    And credits 1
    When I start a session for scope "Test scope"
    Then the engine records a canonical_id for every root derived from normalized statement text
    And canonical_id does not depend on the input ordering of roots

  Scenario: Closed-world mode omits H_other
    Given default config:
      | tau     | 0.70 |
      | epsilon | 0.05 |
      | gamma   | 0.20 |
      | alpha   | 0.40 |
      | beta    | 1.00 |
      | W       | 3.00 |
      | lambda_voi | 0.10 |
      | world_mode | closed |
    Given a hypothesis set with named roots:
      | id   | statement          | exclusion_clause                |
      | H1   | Alpha mechanism    | Not explained by any other root |
      | H2   | Beta mechanism     | Not explained by any other root |
    And credits 1
    When I start a session for scope "Closed world"
    Then the session does not contain root "H_other"
