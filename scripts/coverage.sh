#!/bin/sh
set -e

coverage erase
coverage run -m pytest -q -m "not e2e"
coverage run -a -m behave --steps-directory tests/bdd/steps tests/bdd/features
coverage combine
coverage report --show-missing --fail-under=100
