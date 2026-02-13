# tests/bdd/features/37_quote_fidelity_discriminator_gate.feature
Feature: Quote fidelity and discriminator admission
  # Benefit: quote fidelity checks should be robust to harmless formatting/
  # Unicode/control-character variation, and quote mismatches should degrade
  # confidence provenance without necessarily erasing otherwise valid typed
  # discriminator evidence.

  Scenario: Tolerant quote normalization accepts Unicode and control-char variants
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
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And quote fidelity gate mode is "strict"
    And evidence item "ref1" text is "Instructor’s briefing was complete."
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                                                                    |
      | p                      | 0.90                                                                                                                     |
      | A                      | 2                                                                                                                        |
      | B                      | 2                                                                                                                        |
      | C                      | 2                                                                                                                        |
      | D                      | 2                                                                                                                        |
      | evidence_ids           | ref1                                                                                                                     |
      | discriminator_ids      | d12                                                                                                                      |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                           |
      | quotes                 | [{"evidence_id":"ref1","exact_quote":"Instructor's   briefing\u000bwas complete."}]                             |
      | non_discriminative     | false                                                                                                                    |
      | entailment             | SUPPORTS                                                                                                                 |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And the audit log does not record policy warning "MISSING_ACTIVE_DISCRIMINATOR"
    And the audit log does not record event "QUOTE_FIDELITY_DEGRADED"

  # Benefit: advisory mode preserves typed contrastive signal when quote
  # extraction is imperfect, while still emitting explicit audit degradation.
  Scenario: Advisory quote-fidelity mode does not erase valid typed discriminators
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
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And quote fidelity gate mode is "advisory"
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                                                                    |
      | p                      | 0.90                                                                                                                     |
      | A                      | 2                                                                                                                        |
      | B                      | 2                                                                                                                        |
      | C                      | 2                                                                                                                        |
      | D                      | 2                                                                                                                        |
      | evidence_ids           | ref1                                                                                                                     |
      | discriminator_ids      | d12                                                                                                                      |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                           |
      | quotes                 | [{"evidence_id":"ref1","exact_quote":"Completely different quote."}]                                             |
      | non_discriminative     | false                                                                                                                    |
      | entailment             | SUPPORTS                                                                                                                 |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And the audit log records event "QUOTE_FIDELITY_DEGRADED"
    And the audit log does not record policy warning "MISSING_ACTIVE_DISCRIMINATOR"

  # Benefit: strict mode remains available for workflows that require quote
  # provenance to be exact before admitting contrastive evidence.
  Scenario: Strict quote-fidelity mode blocks active discriminator on quote mismatch
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
      | root_a | root_b | discriminator                     |
      | H1     | H2     | Observable X separates H1 from H2 |
    And strict contrastive updates are required
    And typed discriminator evidence is required
    And quote fidelity gate mode is "strict"
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                                                                    |
      | p                      | 0.90                                                                                                                     |
      | A                      | 2                                                                                                                        |
      | B                      | 2                                                                                                                        |
      | C                      | 2                                                                                                                        |
      | D                      | 2                                                                                                                        |
      | evidence_ids           | ref1                                                                                                                     |
      | discriminator_ids      | d12                                                                                                                      |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}]                           |
      | quotes                 | [{"evidence_id":"ref1","exact_quote":"Completely different quote."}]                                             |
      | non_discriminative     | false                                                                                                                    |
      | entailment             | SUPPORTS                                                                                                                 |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log does not record event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And the audit log records event "QUOTE_FIDELITY_DEGRADED"
    And the audit log records policy warning "MISSING_ACTIVE_DISCRIMINATOR"
