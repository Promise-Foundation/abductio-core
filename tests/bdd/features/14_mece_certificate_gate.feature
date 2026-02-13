# tests/bdd/features/14_mece_certificate_gate.feature
Feature: Strict MECE certificate gating
  In strict mode, sessions must provide pairwise overlap bounds and pairwise
  discriminators for every named-root pair before credit spending begins.

  Background:
    Given default config:
      | tau        | 0.70 |
      | epsilon    | 0.05 |
      | gamma      | 0.20 |
      | alpha      | 0.40 |
      | beta       | 1.00 |
      | W          | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |

  Scenario: Strict MECE certificate passes when pair coverage is complete and bounded
    Given a hypothesis set with named roots:
      | id | statement   | exclusion_clause                |
      | H1 | Mechanism A | Not explained by any other root |
      | H2 | Mechanism B | Not explained by any other root |
      | H3 | Mechanism C | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 0     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                               |
      | H1     | H2     | TRP miss without alert favors H1 over H2    |
      | H1     | H3     | Marking adequacy evidence separates H1 and H3 |
      | H2     | H3     | Crew challenge behavior separates H2 and H3 |
    And credits 1
    When I start a session for scope "Strict MECE gate pass"
    Then stop_reason is "None"
    And no operations were executed
    And the audit log records MECE certificate status "PASSED"

  Scenario: Strict MECE certificate fails when overlap exceeds the allowed bound
    Given a hypothesis set with named roots:
      | id | statement   | exclusion_clause                |
      | H1 | Mechanism A | Not explained by any other root |
      | H2 | Mechanism B | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 0.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 2     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                        |
      | H1     | H2     | Distinct stop-point evidence exists |
    And credits 1
    When I start a session for scope "Strict MECE overlap fail"
    Then stop_reason is "MECE_CERTIFICATE_FAILED"
    And no operations were executed
    And the audit log records MECE certificate status "FAILED"
    And the audit log records a MECE certificate issue containing "pair_overlap_exceeds_threshold"

  Scenario: Strict MECE certificate fails when pairwise discriminator coverage is incomplete
    Given a hypothesis set with named roots:
      | id | statement   | exclusion_clause                |
      | H1 | Mechanism A | Not explained by any other root |
      | H2 | Mechanism B | Not explained by any other root |
      | H3 | Mechanism C | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
      | H1     | H3     | 1     |
      | H2     | H3     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                               |
      | H1     | H2     | TRP miss without alert favors H1 over H2    |
      | H1     | H3     | Marking adequacy evidence separates H1 and H3 |
    And credits 1
    When I start a session for scope "Strict MECE discriminator fail"
    Then stop_reason is "MECE_CERTIFICATE_FAILED"
    And no operations were executed
    And the audit log records MECE certificate status "FAILED"
    And the audit log records a MECE certificate issue containing "missing_pairwise_discriminator"
