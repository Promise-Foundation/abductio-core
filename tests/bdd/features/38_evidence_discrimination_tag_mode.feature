# tests/bdd/features/38_evidence_discrimination_tag_mode.feature
Feature: Evidence discrimination tag mode
  # Benefit: strict contrastive runs can require exhaustive per-evidence tags
  # when desired, while default targeted mode accepts typed discriminator
  # payloads without forcing every supportive citation to be contrastive-tagged.

  Scenario: Targeted mode admits typed discriminator with untagged background evidence
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
    And evidence discrimination tags are required
    And evidence discrimination tag mode is "targeted"
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                             |
      | p                      | 0.90                                                                              |
      | A                      | 2                                                                                 |
      | B                      | 2                                                                                 |
      | C                      | 2                                                                                 |
      | D                      | 2                                                                                 |
      | evidence_ids           | ref1,ref2,ref3                                                                    |
      | discriminator_ids      | d12                                                                               |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}] |
      | non_discriminative     | false                                                                             |
      | entailment             | SUPPORTS                                                                          |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log records event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And audit event "EVIDENCE_DISCRIMINATION_TAGS_MISSING" payload field "blocking" equals "False"
    And audit event "EVIDENCE_DISCRIMINATION_TAGS_MISSING" payload field "tag_mode" equals "targeted"
    And the audit log does not record policy warning "MISSING_EVIDENCE_DISCRIMINATION_TAGS"

  Scenario: Exhaustive mode blocks typed discriminator when background evidence is untagged
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
    And evidence discrimination tags are required
    And evidence discrimination tag mode is "exhaustive"
    And a scoped root "H1"
    And slot node "H1:availability" has initial p = 0.50
    And a deterministic evaluator that returns for node "H1:availability":
      | key                    | value                                                                             |
      | p                      | 0.90                                                                              |
      | A                      | 2                                                                                 |
      | B                      | 2                                                                                 |
      | C                      | 2                                                                                 |
      | D                      | 2                                                                                 |
      | evidence_ids           | ref1,ref2,ref3                                                                    |
      | discriminator_ids      | d12                                                                               |
      | discriminator_payloads | [{"id":"d12","pair":"H1/H2","direction":"FAVORS_LEFT","evidence_ids":["ref1"]}] |
      | non_discriminative     | false                                                                             |
      | entailment             | SUPPORTS                                                                          |
    And credits 1
    When I run the engine for exactly 1 evaluation targeting "H1:availability"
    Then the audit log does not record event "DISCRIMINATOR_EVIDENCE_RECORDED"
    And audit event "EVIDENCE_DISCRIMINATION_TAGS_MISSING" payload field "blocking" equals "True"
    And audit event "EVIDENCE_DISCRIMINATION_TAGS_MISSING" payload field "tag_mode" equals "exhaustive"
    And the audit log records policy warning "MISSING_EVIDENCE_DISCRIMINATION_TAGS"
