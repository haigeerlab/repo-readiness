#!/bin/bash
# Full local check: unit tests on the default python3, then again on the
# macOS system interpreter (3.9) when it exists, so 3.10+ syntax cannot slip in.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

run_tests() {
  echo "== tests on $1 ($("$1" --version 2>&1))"
  PYTHONPATH="$here/src" "$1" -m unittest discover -s tests </dev/null
}

run_tests python3
if [ -x /usr/bin/python3 ] && [ "$(command -v python3)" != /usr/bin/python3 ]; then
  run_tests /usr/bin/python3
fi
echo "== validate.sh: ok"
