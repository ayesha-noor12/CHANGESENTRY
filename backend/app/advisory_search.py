"""Advisory lookup for dependencies added or re-pinned by a change.

Two sources with different strength of evidence:
- OSV (api.osv.dev) answers "is this exact version listed as affected?" - a verified match.
- Tavily web search returns leads (titles, URLs, snippets) that a human should read;
  a search hit alone is never treated as proof that the version is vulnerable.
"""
import re

import requests

from app.config import env
from app.models import AdvisoryResult, DependencyAdvisory, OsvVuln

REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(==|>=|~=)\s*([A-Za-z0-9.*+!_-]+)")
ADVISORY_DOMAINS = ["osv.dev", "nvd.nist.gov", "github.com", "security.snyk.io", "pypi.org"]


def parse_requirements(text: str | None) -> dict[str, str]:
    pins = {}
    for line in (text or "").splitlines():
        match = REQUIREMENT.match(line.split("#", 1)[0])
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(3)
    return pins


def changed_dependencies(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str | None, str]]:
    changes = []
    for path in sorted(after):
        if not re.search(r"(^|/)requirements[^/]*\.txt$", path):
            continue
        old, new = parse_requirements(before.get(path)), parse_requirements(after[path])
        for name, version in sorted(new.items()):
            if old.get(name) != version:
                changes.append((name, old.get(name), version))
    return changes


def query_osv(name: str, version: str) -> tuple[str, list[OsvVuln], str | None]:
    try:
        response = requests.post(
            "https://api.osv.dev/v1/query",
            json={"package": {"name": name, "ecosystem": "PyPI"}, "version": version},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return "error", [], f"OSV request failed: {type(exc).__name__}"
    vulns, seen = [], set()
    for v in response.json().get("vulns", []):
        # OSV lists the same issue under several ids (GHSA, PYSEC); keep the first record of each.
        ids = {v["id"], *v.get("aliases", [])}
        if ids & seen:
            continue
        seen |= ids
        vulns.append(OsvVuln(
            id=v["id"],
            summary=v.get("summary") or (v.get("details") or "")[:240],
            aliases=v.get("aliases", []),
            url=f"https://osv.dev/vulnerability/{v['id']}",
        ))
    return ("affected" if vulns else "no_known_vulns"), vulns, None


def search_tavily(name: str, version: str) -> tuple[str, str | None, list[AdvisoryResult], str | None]:
    api_key = env("TAVILY_API_KEY")
    query = f'"{name}" "{version}" security advisory CVE affected versions'
    if api_key is None:
        return "not_configured", query, [], "TAVILY_API_KEY is not set"
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_domains": ADVISORY_DOMAINS,
            },
            timeout=20,
        )
        if response.status_code == 429:
            return "error", query, [], "Tavily rate limit reached (HTTP 429)"
        if response.status_code in (401, 403):
            return "error", query, [], f"Tavily rejected the API key (HTTP {response.status_code})"
        response.raise_for_status()
    except requests.RequestException as exc:
        return "error", query, [], f"Tavily request failed: {type(exc).__name__}"
    results = [
        AdvisoryResult(title=item.get("title"), url=item.get("url"), snippet=(item.get("content") or "")[:400])
        for item in response.json().get("results", [])
    ]
    return "ok", query, results, None


def search_advisories(before: dict[str, str], after: dict[str, str]) -> list[DependencyAdvisory]:
    advisories = []
    for name, old, new in changed_dependencies(before, after):
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+!_-]*", new):
            continue
        osv_status, vulns, osv_error = query_osv(name, new)
        tavily_status, query, results, tavily_error = search_tavily(name, new)
        advisories.append(DependencyAdvisory(
            name=name, ecosystem="PyPI", old_version=old, new_version=new,
            osv_status=osv_status, osv_error=osv_error, osv_vulns=vulns,
            tavily_status=tavily_status, tavily_error=tavily_error, tavily_query=query, tavily_results=results,
        ))
    return advisories
