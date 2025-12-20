# tests/bdd/features/12_adapters_cli_api_smoke.feature
Feature: Presentation adapters (CLI/API) do not bypass the application layer
  The CLI and API are thin adapters. They must call the same application use case as library consumers.
  (This is a "contract" feature; you can implement adapter tests later, but keep the behavior specified now.)

  Scenario: Library entrypoint runs without reading stdin or requiring a CLI context
    Given a hypothesis set with named roots:
      | id   | statement     | exclusion_clause                |
      | H1   | Mechanism A   | Not explained by any other root |
    And credits 1
    When I call the application run use case directly as a library function
    Then I get a SessionResult object with:
      | field |
      | roots |
      | ledger |
      | audit |
      | stop_reason |
      | credits_remaining |

  Scenario: CLI adapter uses the same application use case (integration seam)
    Given the CLI adapter is configured with an application runner instance
    When the CLI adapter is invoked with args that specify claim and credits
    Then the CLI adapter calls exactly one application run use case
    And the CLI output is derived only from SessionResult (no domain/infrastructure leakage)

  Scenario: API adapter uses the same application use case (integration seam)
    Given the API adapter is configured with an application runner instance
    When the API endpoint is called with a JSON body specifying claim and config
    Then the API adapter calls exactly one application run use case
    And the API response is derived only from SessionResult
