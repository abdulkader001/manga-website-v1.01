"""Read the React app's source to learn what it calls and which pages it guards.

Used by ``tests/test_route_audit.py`` to prove the frontend and the backend agree
(every call has a route, every admin tab has a page and the right permission).
It only reads text; nothing here runs the frontend.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
_METHODS = ("get", "post", "put", "patch", "delete")
_CALL = re.compile(r"""\bapi\.(get|post|put|patch|delete)\(\s*(["'`])(/[^"'`]*)\2(\s*\+)?""")


def normalise(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"\{[^}/]*\}", "{}", path)
    return path.rstrip("/") or "/"


def segments_match(call: str, route: str) -> bool:
    a, b = call.strip("/").split("/"), route.strip("/").split("/")
    return len(a) == len(b) and all(y == "{}" or x == "{}" or x == y for x, y in zip(a, b))


def source_files() -> list[Path]:
    return [p for p in SRC.rglob("*.js*") if ".test." not in p.name]


def direct_calls(text: str) -> list[tuple[str, str]]:
    """``api.get("/x")`` style calls: (METHOD, normalised path)."""

    out = []
    for m in _CALL.finditer(text):
        if m.group(4):  # "/a/" + id: not a whole path
            continue
        out.append((m.group(1).upper(), normalise(m.group(3))))
    return out


def helper_map() -> dict[str, list[tuple[str, str]]]:
    """``admin.permissions.mine`` -> [("GET", "/admin/permissions/me")] from services/api.js."""

    lines = (SRC / "services" / "api.js").read_text().splitlines()
    stack: list[tuple[int, str]] = []
    out: dict[str, list[tuple[str, str]]] = {}
    key_line = re.compile(r"^(\s*)(\w+): ?(.*)$")
    for i, line in enumerate(lines):
        m = key_line.match(line)
        if not m:
            continue
        indent, key, rest = len(m.group(1)), m.group(2), m.group(3)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if rest.rstrip().endswith("{") and "=>" not in rest:
            stack.append((indent, key))
            continue
        if "=>" in rest:
            chunk = rest
            j = i + 1
            while j < len(lines) and not key_line.match(lines[j]) and j < i + 8:
                chunk += "\n" + lines[j]
                j += 1
            calls = direct_calls(chunk)
            if calls:
                out[".".join([k for _, k in stack] + [key]).removeprefix("api.")] = calls
    return out


def page_calls(text: str, helpers: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str]]:
    calls = list(direct_calls(text))
    for m in re.finditer(r"\bapi\.([A-Za-z_][\w.]*)\(", text):
        name = m.group(1)
        if name in helpers:
            calls += helpers[name]
    return calls


# ---------------------------------------------------------------- admin tabs


def feature_links() -> list[dict]:
    """``ADMIN_FEATURE_LINKS`` from src/constants/adminFeatures.js."""

    text = (SRC / "constants" / "adminFeatures.js").read_text()
    out = []
    for block in re.findall(r"\{\s*key:.*?\n  \}", text, re.S):
        def field(name: str) -> str | None:
            m = re.search(rf"\b{name}:\s*\"([^\"]*)\"", block)
            return m.group(1) if m else None

        out.append(
            {
                "key": field("key"),
                "to": field("to"),
                "minRole": field("minRole"),
                "permission": field("permission"),
            }
        )
    return out


def admin_routes() -> list[dict]:
    """Every ``/admin...`` route in src/app.js with its AuthGuard flags and page file."""

    text = (SRC / "app.js").read_text()
    imports = {}
    for m in re.finditer(r'(?:import (\w+) from|const (\w+) = React\.lazy\(\(\) => import\()\s*"\./([^"]+)"', text):
        imports[m.group(1) or m.group(2)] = m.group(3)
    out = []
    for m in re.finditer(
        r'path="(/admin[^"]*)"\s*element=\{\s*<AuthGuard([^>]*)>\s*<(\w+)', text, re.S
    ):
        attrs = m.group(2)
        perm = re.search(r'permission="([^"]+)"', attrs)
        file = imports.get(m.group(3))
        out.append(
            {
                "path": m.group(1),
                "permission": perm.group(1) if perm else None,
                "main_admin_only": "requireMainAdmin" in attrs,
                "component": m.group(3),
                "file": next(iter(SRC.glob(f"{file}.js*")), None) if file else None,
            }
        )
    return out


def imported_files(file: Path, depth: int = 2) -> list[Path]:
    """The file plus the local files it imports (a page's panels call APIs too)."""

    seen: list[Path] = []

    def walk(path: Path, left: int) -> None:
        if path in seen or not path.exists():
            return
        seen.append(path)
        if left == 0:
            return
        text = path.read_text()
        for m in re.finditer(r'from "(\.{1,2}/[^"]+)"', text):
            target = (path.parent / m.group(1)).resolve()
            for candidate in (target, *[target.with_suffix(s) for s in (".js", ".jsx")], target / "index.js"):
                if candidate.is_file():
                    # Only the page's own panels: not the shared services, hooks
                    # and contexts, which every page imports.
                    if candidate.relative_to(SRC).parts[0] in ("pages", "components"):
                        walk(candidate, left - 1)
                    break

    walk(file, depth)
    return seen
