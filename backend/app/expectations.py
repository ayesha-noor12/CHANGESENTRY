"""Find evidence, in the base revision, that a template's invariant is an established requirement.

A base-pass/head-fail result only shows that behaviour changed. It becomes a
confirmed regression when the base revision itself already states or enforces
the invariant. Evidence is collected deterministically here, never from the model.
"""
import re

from app.models import RequirementEvidence
from app.repository_analyzer import GUARD_PATTERN, RepoIndex

NONNEGATIVE_PATTERN = re.compile(
    r"never (?:be )?(?:negative|below zero)|must not be negative|non-?negative|at or above zero", re.I)
MAX_EVIDENCE = 4


def find_requirements(template: str, target: str, base: RepoIndex, head: RepoIndex) -> list[RequirementEvidence]:
    if template == "auth_guard":
        return _guarded_peers(target, base, head)
    if template == "nonnegative_total":
        return _stated_nonnegative(target, base, head)
    return []


def _guarded_peers(route: str, base: RepoIndex, head: RepoIndex) -> list[RequirementEvidence]:
    """Base routes that call the same operations as the target route only after an auth guard."""
    evidence = []
    base_route = base.routes().get(route)
    head_fn = head.routes().get(route)
    if base_route:
        guard = _first_guard(base_route)
        if guard:
            evidence.append(RequirementEvidence(
                kind="enforced_in_base", file=base_route.file, line=guard.line, text=guard.text,
                reason=f"In the base revision, {route} itself calls {guard.target} before doing any work."))
    operations = {c.target for c in (head_fn.calls if head_fn else []) if c.target in base.functions}
    for fn in base.routes().values():
        if fn.route == route:
            continue
        guard = _first_guard(fn)
        shared = sorted(operations & {c.target for c in fn.calls})
        if guard and shared:
            evidence.append(RequirementEvidence(
                kind="enforced_in_base", file=fn.file, line=guard.line, text=guard.text,
                reason=f"In the base revision, {fn.route} calls {', '.join(shared)} only after {guard.target}."))
    return evidence[:MAX_EVIDENCE]


def _first_guard(fn):
    return next((c for c in fn.calls if GUARD_PATTERN.search(c.target.rsplit(":", 1)[-1])), None)


def _stated_nonnegative(target: str, base: RepoIndex, head: RepoIndex) -> list[RequirementEvidence]:
    """Documentation, docstrings or comments in the base revision that state the non-negative rule.

    Searched: docs, the target's module and the modules of every function connected to the
    target by a call in either revision.
    """
    related = {target}
    for index in (base, head):
        if target in index.functions:
            related |= {c.target for c in index.functions[target].calls}
        related |= {fid for fid, fn in index.functions.items() if any(c.target == target for c in fn.calls)}
    files = {base.functions[fid].file for fid in related if fid in base.functions}
    files |= {path for path in base.files if path.startswith("docs/") or path.lower().startswith("readme")}
    evidence = []
    for path in sorted(files):
        for number, line in enumerate(base.files[path].splitlines(), 1):
            if NONNEGATIVE_PATTERN.search(line):
                evidence.append(RequirementEvidence(
                    kind="stated_in_base", file=path, line=number, text=line.strip(),
                    reason="The base revision states that the amount must not be negative."))
    return evidence[:MAX_EVIDENCE]
