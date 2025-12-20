#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/release.sh X.Y.Z"
  exit 1
fi

version="$1"

RELEASE_VERSION="$version" python - <<'PY'
from pathlib import Path
import re
import os

path = Path("pyproject.toml")
text = path.read_text()
version = os.environ["RELEASE_VERSION"]
new_text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', text, count=1)
if count != 1:
    raise SystemExit("Failed to update version in pyproject.toml")
path.write_text(new_text)
PY

git add pyproject.toml

git commit -m "Release v${version}"

git tag "v${version}"

echo "Tagged v${version}. Push with: git push && git push --tags"
