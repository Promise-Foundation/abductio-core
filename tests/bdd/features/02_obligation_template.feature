# tests/bdd/features/02_obligation_template.feature
Feature: Obligation template parity and scoping
  Every named root must instantiate the same obligation slots before being considered SCOPED.
  Failure to instantiate marks the root UNSCOPED and caps confidence.

  Background:
    Given default config:
      | tau     | 0.70 |
      | epsilon | 0.05 |
      | gamma   | 0.20 |
      | alpha   | 0.40 |
      | beta    | 1.00 |
      | W       | 3.00 |
      | lambda_voi | 0.10 |
    And required template slots:
      | slot_key            | role |
      | availability        | NEC  |
      | fit_to_key_features | NEC  |
      | defeater_resistance | NEC  |

  Scenario: First DECOMPOSE on an UNSCOPED root instantiates the template
    Given a hypothesis set with named roots:
      | id   | statement                      | exclusion_clause                |
      | H1   | Mechanism A                    | Not explained by any other root |
      | H2   | Mechanism B                    | Not explained by any other root |
    And a deterministic decomposer that will scope roots with:
      | root_id | availability_statement     | fit_statement            | defeater_statement              |
      | H1      | A present at time/place    | A explains key reports   | A survives main defeater        |
      | H2      | B present at time/place    | B explains key reports   | B survives main defeater        |
    And credits 2
    When I run the engine until credits exhausted
    Then both "H1" and "H2" become status "SCOPED"
    And each root has exactly the required template slots
    And each unassessed NEC slot has p = 0.5 and k = 0.15

  Scenario: Root that cannot be scoped is UNSCOPED and k is capped
    Given a hypothesis set with named roots:
      | id   | statement                         | exclusion_clause                |
      | H1   | Mechanism A                       | Not explained by any other root |
      | H2   | Vague umbrella explanation         | Not explained by any other root |
    And a deterministic decomposer that fails to scope root "H2"
    And credits 2
    When I run the engine until credits exhausted
    Then root "H2" remains status "UNSCOPED"
    And root "H2" has k_root <= 0.40
    And the audit log records that UNSCOPED capping was applied
