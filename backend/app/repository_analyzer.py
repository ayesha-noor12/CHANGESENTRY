"""Diff, AST index and impact graph for a fixture's before/after versions.

The call graph is built from static imports and direct calls only. Dynamic
dispatch, reflection and aliasing can hide relationships, so any edge that is
matched by name rather than through a resolved import is labelled "candidate".
"""
import ast
import difflib
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from app.models import ChangedFile, DeterministicSignal, GraphEdge, GraphNode, ImpactGraph

TEXT_SUFFIXES = {".py", ".txt", ".md", ".toml", ".cfg", ".json", ".yaml", ".yml", ".ini"}
GUARD_PATTERN = re.compile(r"^(require|check|verify|ensure|authorize|authenticate)_|auth|permission", re.I)
NUMERIC_ANNOTATIONS = {"float", "int"}
MAX_GRAPH_DEPTH = 3
MAX_GRAPH_NODES = 40


def read_tree(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix not in TEXT_SUFFIXES:
            continue
        files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return files


def language_for(path: str) -> str:
    return {".py": "python", ".md": "markdown", ".txt": "text", ".json": "json"}.get(Path(path).suffix, "text")


def compute_changes(before: dict[str, str], after: dict[str, str]) -> list[ChangedFile]:
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        change_type = "added" if old is None else "deleted" if new is None else "modified"
        old_lines = (old or "").splitlines()
        new_lines = (new or "").splitlines()
        diff_lines = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile="/dev/null" if old is None else f"a/{path}",
            tofile="/dev/null" if new is None else f"b/{path}",
            lineterm="", n=3,
        ))
        added_lines = []
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                added_lines.extend(range(j1 + 1, j2 + 1))
        changes.append(ChangedFile(
            path=path,
            change_type=change_type,
            language=language_for(path),
            additions=sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")),
            deletions=sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---")),
            diff="\n".join(diff_lines),
            added_lines=added_lines,
        ))
    return changes


# ---------------------------------------------------------------- AST index

@dataclass
class CallSite:
    target: str          # fully-qualified function id, or a bare name if unresolved
    line: int
    resolved: bool
    text: str


@dataclass
class FunctionInfo:
    id: str              # module:qualname
    module: str
    name: str
    file: str
    line: int
    end_line: int
    route: str | None = None
    params: list[tuple[str, str | None]] = field(default_factory=list)
    body_keys: list[str] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)


@dataclass
class ModuleInfo:
    name: str
    file: str
    imports: dict[str, str] = field(default_factory=dict)  # local alias -> fq module or module.symbol
    import_lines: dict[str, int] = field(default_factory=dict)


@dataclass
class RepoIndex:
    files: dict[str, str]
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    functions: dict[str, FunctionInfo] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)

    def module_for_file(self, path: str) -> ModuleInfo | None:
        return next((m for m in self.modules.values() if m.file == path), None)

    def routes(self) -> dict[str, FunctionInfo]:
        return {f.route: f for f in self.functions.values() if f.route}

    def numeric_functions(self) -> dict[str, FunctionInfo]:
        """Functions whose every parameter is annotated int/float (eligible for nonnegative_total)."""
        return {
            fid: f for fid, f in self.functions.items()
            if f.params and all(ann in NUMERIC_ANNOTATIONS for _, ann in f.params)
        }

    def excerpt(self, fid: str) -> str:
        fn = self.functions[fid]
        lines = self.files[fn.file].splitlines()
        start = fn.line
        return "\n".join(f"{n:>4} | {lines[n - 1]}" for n in range(start, min(fn.end_line, len(lines)) + 1))


def module_name(path: str) -> str:
    parts = Path(path).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(module: str, is_package: bool, level: int, target: str | None) -> str:
    base = module.split(".") if is_package else module.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join(base + ([target] if target else []))


def _route_from_decorator(dec: ast.expr) -> str | None:
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    if name not in {"route", "get", "post", "put", "delete", "patch"}:
        return None
    if not dec.args or not isinstance(dec.args[0], ast.Constant) or not isinstance(dec.args[0].value, str):
        return None
    method = "GET" if name == "route" else name.upper()
    for kw in dec.keywords:
        if kw.arg == "method" and isinstance(kw.value, ast.Constant):
            method = str(kw.value.value).upper()
    return f"{method} {dec.args[0].value}"


def _body_keys(node: ast.AST) -> list[str]:
    """Payload keys read as request.body.get("k") or request.body["k"]."""
    keys = []
    for sub in ast.walk(node):
        target = None
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "get":
            target, arg = sub.func.value, (sub.args[0] if sub.args else None)
        elif isinstance(sub, ast.Subscript):
            target, arg = sub.value, sub.slice
        else:
            continue
        if (isinstance(target, ast.Attribute) and target.attr in {"body", "json"}
                and isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value not in keys):
            keys.append(arg.value)
    return keys


def build_index(files: dict[str, str]) -> RepoIndex:
    index = RepoIndex(files=files)
    trees = {}
    for path, source in files.items():
        if not path.endswith(".py"):
            continue
        try:
            trees[path] = ast.parse(source, filename=path)
        except SyntaxError as exc:
            index.parse_errors.append(f"{path}:{exc.lineno}: {exc.msg}")
            continue
        index.modules[module_name(path)] = ModuleInfo(name=module_name(path), file=path)

    for path, tree in trees.items():
        mod = index.modules[module_name(path)]
        is_package = path.endswith("__init__.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod.imports[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
                    mod.import_lines[alias.asname or alias.name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                source_mod = _resolve_relative(mod.name, is_package, node.level, node.module) if node.level else (node.module or "")
                for alias in node.names:
                    local = alias.asname or alias.name
                    mod.imports[local] = f"{source_mod}.{alias.name}"
                    mod.import_lines[local] = node.lineno
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _index_function(index, mod, node, files[path])
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _index_function(index, mod, item, files[path], prefix=f"{node.name}.")

    # Resolve call targets now that every function is known.
    by_name: dict[str, list[str]] = {}
    for fid, fn in index.functions.items():
        by_name.setdefault(fn.name, []).append(fid)
    for fn in index.functions.values():
        mod = index.modules[fn.module]
        for call in fn.calls:
            call.target, call.resolved = _resolve_call(index, mod, call.target, by_name)
    return index


def _index_function(index: RepoIndex, mod: ModuleInfo, node, source: str, prefix: str = "") -> None:
    fid = f"{mod.name}:{prefix}{node.name}"
    route = next((r for r in (_route_from_decorator(d) for d in node.decorator_list) if r), None)
    params = [(a.arg, ast.unparse(a.annotation) if a.annotation else None)
              for a in node.args.args if a.arg not in ("self", "cls")]
    fn = FunctionInfo(
        id=fid, module=mod.name, name=prefix + node.name, file=mod.file, line=node.lineno,
        end_line=node.end_lineno or node.lineno, route=route, params=params, body_keys=_body_keys(node),
    )
    lines = source.splitlines()
    # Walk the body only: decorators such as @route(...) are registration, not calls made by the function.
    body_nodes = (sub for stmt in node.body for sub in ast.walk(stmt))
    for sub in body_nodes:
        if isinstance(sub, ast.Call):
            dotted = _dotted(sub.func)
            if dotted:
                fn.calls.append(CallSite(target=dotted, line=sub.lineno, resolved=False,
                                         text=lines[sub.lineno - 1].strip()))
    index.functions[fid] = fn


def _dotted(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return f"{base}.{expr.attr}" if base else None
    return None


def _resolve_call(index: RepoIndex, mod: ModuleInfo, dotted: str, by_name: dict[str, list[str]]) -> tuple[str, bool]:
    head, _, rest = dotted.partition(".")
    candidates = []
    if head in mod.imports:
        fq = mod.imports[head] + (f".{rest}" if rest else "")
        candidates.append(fq)
    candidates.append(f"{mod.name}.{dotted}")
    for fq in candidates:
        module_part, _, func_part = fq.rpartition(".")
        fid = f"{module_part}:{func_part}"
        if fid in index.functions:
            return fid, True
    # Unresolved: match by bare function name only if exactly one definition exists.
    leaf = dotted.rsplit(".", 1)[-1]
    matches = by_name.get(leaf, [])
    if len(matches) == 1 and "." in dotted:
        return matches[0], False
    return dotted, False


# ---------------------------------------------------------------- impact graph

def changed_function_ids(index: RepoIndex, changes: list[ChangedFile]) -> set[str]:
    changed = set()
    by_file = {c.path: c for c in changes}
    for fid, fn in index.functions.items():
        change = by_file.get(fn.file)
        if change is None:
            continue
        if change.change_type == "added" or any(fn.line <= ln <= fn.end_line for ln in change.added_lines):
            changed.add(fid)
    return changed


def build_graph(index: RepoIndex, changes: list[ChangedFile]) -> tuple[ImpactGraph, set[str]]:
    changed = changed_function_ids(index, changes)
    forward: dict[str, list[tuple[str, CallSite]]] = {}
    reverse: dict[str, list[tuple[str, CallSite]]] = {}
    for fid, fn in index.functions.items():
        for call in fn.calls:
            if call.target in index.functions and call.target != fid:
                forward.setdefault(fid, []).append((call.target, call))
                reverse.setdefault(call.target, []).append((fid, call))

    depth = {fid: 0 for fid in changed}
    queue = deque(sorted(changed))
    while queue and len(depth) < MAX_GRAPH_NODES:
        current = queue.popleft()
        if depth[current] >= MAX_GRAPH_DEPTH:
            continue
        for neighbour, _ in forward.get(current, []) + reverse.get(current, []):
            if neighbour not in depth:
                depth[neighbour] = depth[current] + 1
                queue.append(neighbour)

    nodes = []
    for fid, d in depth.items():
        fn = index.functions[fid]
        nodes.append(GraphNode(
            id=fid, label=fn.name, kind="route" if fn.route else "function", file=fn.file,
            line=fn.line, changed=fid in changed, route=fn.route, depth=d,
        ))
    edges, seen = [], set()
    for fid in depth:
        for target, call in forward.get(fid, []):
            key = (fid, target)
            if target in depth and key not in seen:
                seen.add(key)
                edges.append(GraphEdge(
                    id=f"{fid}->{target}", source=fid, target=target, kind="calls",
                    confidence="resolved" if call.resolved else "candidate",
                    evidence=f"{index.functions[fid].file}:{call.line}: {call.text}",
                ))

    # Changed non-Python files (manifests, docs) are shown as file nodes.
    for change in changes:
        if change.language == "python":
            continue
        node_id = f"file:{change.path}"
        nodes.append(GraphNode(id=node_id, label=change.path, kind="file", file=change.path, changed=True))
    # Changed module-level code (e.g. a new import that registers routes) is shown as a file node.
    for change in changes:
        if change.language != "python" or change.change_type == "deleted":
            continue
        mod = index.module_for_file(change.path)
        if mod is None:
            continue
        in_function = {ln for f in index.functions.values() if f.file == change.path
                       for ln in range(f.line, f.end_line + 1)}
        if any(ln not in in_function for ln in change.added_lines):
            node_id = f"file:{change.path}"
            nodes.append(GraphNode(id=node_id, label=change.path, kind="file", file=change.path, changed=True))
            lines = index.files[change.path].splitlines()
            for local, fq in mod.imports.items():
                line_no = mod.import_lines.get(local, 0)
                if line_no not in change.added_lines:
                    continue
                for fid in depth:
                    if index.functions[fid].module == fq or fq.startswith(index.functions[fid].module + "."):
                        key = (node_id, fq)
                        if key in seen:
                            continue
                        seen.add(key)
                        edges.append(GraphEdge(
                            id=f"{node_id}->{fid}", source=node_id, target=fid, kind="imports",
                            confidence="resolved",
                            evidence=f"{change.path}:{line_no}: {lines[line_no - 1].strip()}",
                        ))
    return ImpactGraph(nodes=nodes, edges=edges), changed


# ---------------------------------------------------------------- deterministic rule

def guard_consistency(index: RepoIndex, changed: set[str]) -> list[DeterministicSignal]:
    """Flag a changed route that calls a function which every other caller route guards.

    This is a heuristic signal, not a finding: it only says the new code path differs
    from the established pattern.
    """
    def guards_of(fn: FunctionInfo) -> list[str]:
        return [c.target for c in fn.calls if GUARD_PATTERN.search(c.target.rsplit(":", 1)[-1])]

    routes = [f for f in index.functions.values() if f.route]
    signals = []
    for fn in routes:
        if fn.id not in changed or guards_of(fn):
            continue
        for call in fn.calls:
            if call.target not in index.functions or GUARD_PATTERN.search(call.target):
                continue
            peers = [r for r in routes if r.id != fn.id and any(c.target == call.target for c in r.calls)]
            guarded_peers = [r for r in peers if guards_of(r)]
            if peers and len(guarded_peers) == len(peers):
                peer = guarded_peers[0]
                guard = guards_of(peer)[0]
                signals.append(DeterministicSignal(
                    rule="guard-consistency",
                    file=fn.file,
                    line=call.line,
                    symbol=fn.id,
                    message=(f"Route {fn.route} calls {call.target} without a guard; every other route "
                             f"calling it ({', '.join(p.route for p in peers)}) first calls {guard}."),
                    evidence=f"{fn.file}:{call.line}: {call.text}",
                    suggested_template="auth_guard",
                    suggested_target=fn.route,
                ))
    return signals


def sample_payload(keys: list[str]) -> dict:
    """Plausible values for payload keys a handler reads, so validation does not mask the code path."""
    payload = {}
    for key in keys:
        if re.search(r"amount|total|price|qty|quantity|count", key, re.I):
            payload[key] = 10.0
        elif key.endswith("order_id"):
            payload[key] = "ord_1001"
        else:
            payload[key] = f"sample-{key}"
    return payload
