from __future__ import annotations

from tests.bdd.steps.support.step_world import StepWorld


def before_scenario(context, scenario) -> None:
    context.world = StepWorld()
