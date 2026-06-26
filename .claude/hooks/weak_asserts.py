#!/usr/bin/env python3
"""PreToolUse(Edit|Write) guard against green-washing tests.

A test whose every assertion is trivially true (`assert True`, `== True`,
`is not None`) cannot catch a real bug. We block it before it lands. Inspects the
*proposed* content (Write.content / Edit.new_string), so it fires pre-write.

Exit 2 → block + show message to the model. Heuristic, intentionally strict.
"""

from __future__ import annotations

import json
import re
import sys

TEST_FILE = re.compile(r"(^|/)(test_[^/]+|[^/]+_test)\.py$")
ASSERT_LINE = re.compile(r"^\s*assert\s+(.+?)\s*$", re.M)
DEF_TEST = re.compile(r"^\s*(async\s+)?def\s+test_", re.M)
WEAK = re.compile(r"^(True|.+==\s*True|.+\bis\s+not\s+None|.+\bis\s+None)$")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    ti = data.get("tool_input", {})
    fp = ti.get("file_path", "")
    if not TEST_FILE.search(fp):
        return 0

    content = ti.get("content")
    if content is None:
        content = ti.get("new_string", "")
    if not content or not DEF_TEST.search(content):
        return 0

    asserts = [a.strip() for a in ASSERT_LINE.findall(content)]
    if not asserts:
        print(
            "test assertions too weak: this test file defines tests but has no asserts. "
            "Assert on real behaviour/values.",
            file=sys.stderr,
        )
        return 2

    if all(WEAK.match(a) for a in asserts):
        print(
            "test assertions too weak: every assertion is trivially true "
            "(True / == True / is (not) None). Assert on real values, error types, "
            "or retrieved symbols — a test that cannot fail is dead weight.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
