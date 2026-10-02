"""F-94: no ``async def`` route handler touches the database session directly.

A blocking SQLAlchemy call inside an ``async`` handler stalls that worker's
event loop for every other request. Database work in async handlers must go
through ``run_in_db_threadpool`` (or the handler must be a plain ``def``,
which FastAPI already runs in its thread pool). Nested helper functions are
fine: they are what gets handed to the thread pool.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[1] / "app" / "api" / "routers"

# Reviewed exceptions: these call an *awaited* async wrapper that offloads its
# own work, which the scan cannot tell apart from a blocking call.
ALLOWED = {
    ("auth.py", "request_magic_link_v2"),  # awaits request_magic_link
    ("manga.py", "list_manga"),  # awaits _list_manga_impl
    ("manga.py", "browse_manga"),  # awaits _list_manga_impl
}


def _direct_calls(fn: ast.AST):
    for child in ast.iter_child_nodes(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Await):
            # ``await something(db, ...)`` is an async call, not a blocking one.
            yield from _direct_calls(child.value) if not isinstance(child.value, ast.Call) else ()
            continue
        if isinstance(child, ast.Call):
            yield child
        yield from _direct_calls(child)


def _offenders():
    found = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            sessions = {
                a.arg
                for a in node.args.args + node.args.kwonlyargs
                if a.annotation is not None and "Session" in ast.unparse(a.annotation)
            }
            if not sessions or (path.name, node.name) in ALLOWED:
                continue
            for call in _direct_calls(node):
                func = ast.unparse(call.func)
                if "threadpool" in func:
                    continue
                args = list(call.args) + [k.value for k in call.keywords]
                if any(func.startswith(s + ".") for s in sessions) or any(
                    isinstance(a, ast.Name) and a.id in sessions for a in args
                ):
                    found.append(f"{path.name}:{node.lineno} {node.name} -> {func}")
    return found


def test_async_handlers_do_not_block_on_the_database():
    offenders = _offenders()
    assert not offenders, "Blocking DB calls in async handlers:\n" + "\n".join(offenders)
