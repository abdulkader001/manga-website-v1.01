"""Flat table of every API route with the dependencies that guard it.

FastAPI keeps included routers lazy (``_IncludedRouter``), so the table is
built by walking them and adding the prefix and dependencies each ``include_router``
call contributed (for example the "sign-in required" gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from fastapi.routing import APIRoute


@dataclass(frozen=True)
class RouteInfo:
    methods: tuple[str, ...]
    path: str
    endpoint: str
    module: str
    gates: tuple[str, ...] = field(default_factory=tuple)  # dependency names, outermost first
    powers: tuple[str, ...] = field(default_factory=tuple)  # require_power(...) keys


def _dep_names(dependant, acc: list[str]) -> None:
    call = getattr(dependant, "call", None)
    if call is not None:
        acc.append(getattr(call, "__name__", repr(call)))
        power = getattr(call, "power", None) or getattr(call, "permission", None)
        if power:
            acc.append(f"power:{power}")
    for sub in getattr(dependant, "dependencies", []):
        _dep_names(sub, acc)


def _extra_names(deps: Iterable) -> list[str]:
    out: list[str] = []
    for dep in deps or []:
        call = getattr(dep, "dependency", None)
        if call is not None:
            out.append(getattr(call, "__name__", repr(call)))
            power = getattr(call, "power", None) or getattr(call, "permission", None)
            if power:
                out.append(f"power:{power}")
    return out


def _walk(routes, prefix: str, inherited: list[str], out: list[RouteInfo]) -> None:
    for route in routes:
        if isinstance(route, APIRoute):
            names: list[str] = list(inherited)
            for dep in route.dependant.dependencies:
                _dep_names(dep, names)
            names += _extra_names(getattr(route, "dependencies", []))
            powers = tuple(n.split(":", 1)[1] for n in names if n.startswith("power:"))
            out.append(
                RouteInfo(
                    methods=tuple(sorted(route.methods or ())),
                    path=prefix + route.path,
                    endpoint=route.endpoint.__name__,
                    module=route.endpoint.__module__.rsplit(".", 1)[-1],
                    gates=tuple(n for n in names if not n.startswith("power:")),
                    powers=powers,
                )
            )
            continue
        ctx = getattr(route, "include_context", None)
        original = getattr(route, "original_router", None)
        if ctx is not None and original is not None:
            extra = _extra_names(ctx.dependencies)
            _walk(original.routes, prefix + (ctx.prefix or ""), inherited + extra, out)


def route_table() -> list[RouteInfo]:
    from backend_fastapi.app.bootstrap.routers import build_api_router

    out: list[RouteInfo] = []
    _walk(build_api_router().routes, "", [], out)
    return out
