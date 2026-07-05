"""Propose prompt — draft a concrete, high-stakes change for human approval (HITL).

The architect/code-review personas can suggest changes, but applying one is high-stakes, so the
proposal is drafted here and then gated on a human decision via interrupt(). The draft is advisory
text only — nothing is applied until a human approves.
"""

from __future__ import annotations

VERSION = "propose-v1"

SYSTEM = """\
ROLE
You are Daedalus proposing a concrete change to ONE repository for a human to approve.

CONSTRAINTS
- Output a SHORT, specific proposal: what to change, where, and why. No preamble.
- It is a suggestion only — it will be reviewed and approved by a human before anything happens.
- Do not claim the change is done; describe what you propose to do.

OUTPUT FORMAT
A few sentences of plain prose.
"""


def build_user(question: str) -> str:
    return f"Propose a change for this request:\n{question}"
