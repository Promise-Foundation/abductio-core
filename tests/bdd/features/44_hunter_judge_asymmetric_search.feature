# tests/bdd/features/44_hunter_judge_asymmetric_search.feature
Feature: Hunter and Judge split for asymmetric search with symmetric verification
  # This feature allows adaptive evidence search without dropping final fairness.

  # Benefit: credits are concentrated on high-yield leads before budget exhausts.
  Scenario: Hunter phase loans search credits to the highest saliency contender
    Given default config:
      | tau        | 0.80 |
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
      | id | statement                         | exclusion_clause                |
      | H1 | Procedural deviation caused event | Not explained by any other root |
      | H2 | Mechanical issue caused event      | Not explained by any other root |
      | H3 | Environmental factor caused event  | Not explained by any other root |
    And hunter/judge split is enabled
    And hunter phase search loan credits is 3
    And hunter saliency pre-pass scores are:
      | root_id | saliency |
      | H1      | 0.91     |
      | H2      | 0.38     |
      | H3      | 0.26     |
    And a deterministic searcher with retrieval outcomes:
      | root_id | evidence_ids         |
      | H1      | trp_ref,crew_ref     |
      | H2      | maint_ref            |
      | H3      | weather_ref          |
    And credits 4
    When I run the engine for exactly 4 operations
    Then the audit log records event "HUNTER_SEARCH_LOAN_GRANTED"
    And audit event "HUNTER_SEARCH_LOAN_GRANTED" payload field "target_root_id" equals "H1"
    And audit event "HUNTER_SEARCH_LOAN_GRANTED" payload field "loan_credits" equals "3"

  # Benefit: asymmetry in search does not allow one-sided certification.
  Scenario: Judge phase requires symmetric contrastive verification before certification
    Given default config:
      | tau        | 0.80 |
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
      | id | statement                         | exclusion_clause                |
      | H1 | Procedural deviation caused event | Not explained by any other root |
      | H2 | Mechanical issue caused event      | Not explained by any other root |
    And strict MECE certification is enabled with max pair overlap 1.0
    And pairwise overlap scores:
      | root_a | root_b | score |
      | H1     | H2     | 1     |
    And pairwise discriminators:
      | root_a | root_b | discriminator                                  |
      | H1     | H2     | TRP evidence separates procedural from mechanical |
    And hunter/judge split is enabled
    And hunter phase search loan credits is 2
    And judge phase symmetric verification is required
    And typed discriminator evidence is required
    And a deterministic evaluator with the following outcomes:
      | node_key        | p    | A | B | C | D | evidence_ids | discriminator_ids | discriminator_payloads                                                            | non_discriminative | entailment |
      | H1:availability | 0.90 | 2 | 2 | 2 | 2 | trp_ref      | d12               | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["trp_ref"]}] | false              | SUPPORTS  |
      | H2:availability | 0.62 | 2 | 2 | 2 | 2 | maint_ref    | (empty)           | []                                                                                | true               | SUPPORTS  |
    And credits 4
    When I run the engine until credits exhausted
    Then the top ledger root is "H_UND"
    And the audit log records event "JUDGE_VERIFICATION_REQUIRED"
    And the audit log records event "DECISION_CONTRACT_FAILED"
