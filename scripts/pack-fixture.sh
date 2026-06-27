#!/usr/bin/env bash
# Package the bundled test fixture (backend/sample_repo) into a .zip for the /repos/upload
# flow and UI drag-drop testing. Re-run after editing the fixture.
set -euo pipefail
cd "$(dirname "$0")/../backend"

rm -f sample_repo.zip
zip -rX sample_repo.zip sample_repo \
  -x '*/__pycache__/*' '*.pyc' '*/.DS_Store' >/dev/null
echo "wrote backend/sample_repo.zip ($(du -h sample_repo.zip | cut -f1))"
