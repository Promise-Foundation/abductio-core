# tests/bdd/features/39_counterevidence_credit_reservation.feature
Feature: Counterevidence credit reservation and scheduler preemption
  # Benefit: minimum counterevidence credits represent reserved probe work,
  # not only successful contradictions. This prevents false floor failures
  # when the system spent reserved credits on adversarial checks that did not
  # happen to yield CONTRADICTS.
  Scenario: Counterevidence floor is satisfied by reserved probe credits
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
      | root_a | root_b | discriminator                      |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And decision contract is enabled
    And pair-adjudication queue is enabled
    And pair-adjudication scope is "active_set"
    And pair-adjudication active-set contender count is 2
    And pair-adjudication active-set contender mass ratio floor is 0.00
    And contrastive budget partition is enabled
    And minimum counterevidence credits is 1
    And a scoped root "H1"
    And a scoped root "H2"
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                                                 | non_discriminative | entailment |
      | H1:availability | 0.85 | 2 | 2 | 2 | 2 | ref1         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                      | false              | SUPPORTS  |
      | H2:availability | 0.60 | 2 | 2 | 2 | 2 | ref2         | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_RIGHT","evidence_ids":["ref2"]}]                     | false              | SUPPORTS  |
    And credits 2
    When I run the engine for exactly 2 operations
    Then the audit log records event "COUNTEREVIDENCE_PROBE_CREDIT_RECORDED"
    And the audit log does not record event "COUNTEREVIDENCE_BUDGET_FLOOR_UNMET"

  # Benefit: once only reserved counterevidence credits remain, regular ops
  # are blocked so reservation cannot be silently consumed by decomposition.
  Scenario: Reservation blocks non-counterevidence ops when reserve is tight
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
    And contrastive budget partition is enabled
    And minimum counterevidence credits is 1
    And credits 1
    When I run the engine for exactly 1 operation
    Then stop_reason is "NO_LEGAL_OP"
    And no operations were executed
    And the audit log records event "COUNTEREVIDENCE_RESERVATION_BLOCKED"
