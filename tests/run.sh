#!/usr/bin/env bash
# Run the note-response regression tests.
# Exit 1 when any test reports a regression, 0 when all pass.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1

failed=0

for test_file in "$HERE"/test_*.py; do
    name="$(basename "$test_file" .py)"
    if python3 "$test_file"; then
        printf '%-40s %s\n' "$name" "PASS"
    else
        printf '%-40s %s\n' "$name" "FAIL"
        failed=1
    fi
done

exit "$failed"
