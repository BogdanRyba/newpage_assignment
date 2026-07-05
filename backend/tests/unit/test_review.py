"""merge_findings: flatten reviewer outputs, dedup, severity-sort (pure, no LLM)."""

from __future__ import annotations

from app.domain.review import Finding, ReviewResult, merge_findings


def _f(dim: str, sev: str, title: str, path: str = "a.py") -> Finding:
    return Finding(dimension=dim, severity=sev, title=title, path=path)


def test_dedups_on_path_and_title() -> None:
    merged = merge_findings(
        [
            [_f("security", "high", "SQL injection")],
            [_f("style", "high", "SQL injection")],  # same path+title → deduped
        ]
    )
    assert len(merged) == 1


def test_sorts_high_severity_first() -> None:
    merged = merge_findings(
        [
            [_f("style", "low", "naming", "b.py")],
            [_f("security", "high", "secret in code", "c.py")],
            [_f("performance", "medium", "n+1 query", "d.py")],
        ]
    )
    assert [f.severity for f in merged] == ["high", "medium", "low"]


def test_empty_groups_yield_no_findings() -> None:
    assert merge_findings([[], []]) == []


def test_review_result_summary_counts_by_severity() -> None:
    r = ReviewResult(
        base_ref="main", head_ref="dev", files_reviewed=2,
        findings=[_f("security", "high", "x"), _f("style", "high", "y", "b.py"),
                  _f("style", "low", "z", "c.py")],
    )
    assert r.summary == {"high": 2, "low": 1}
