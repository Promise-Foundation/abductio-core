from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.bdd.steps.support.step_world import StepWorld


def before_scenario(context, scenario) -> None:
    context.world = StepWorld()
