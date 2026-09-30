"""Compatibility layer exposing the upstream ``python_multipart`` package."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Iterable, List

_UPSTREAM_MODULES: tuple[ModuleType, ...] = (
    importlib.import_module("python_multipart"),
    importlib.import_module("python_multipart.multipart"),
)

__all__: List[str] = []


def _export_from(module: ModuleType) -> None:
    """Populate this namespace with public attributes from ``module``."""

    names: Iterable[str]
    module_all = getattr(module, "__all__", None)
    if module_all is not None:
        names = module_all
    else:
        names = (name for name in dir(module) if not name.startswith("_"))

    for name in names:
        if name.startswith("_"):
            continue
        value = getattr(module, name)
        globals()[name] = value
        if name not in __all__:
            __all__.append(name)


for _module in _UPSTREAM_MODULES:
    _export_from(_module)


def __getattr__(name: str):
    for module in _UPSTREAM_MODULES:
        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            if not name.startswith("_") and name not in __all__:
                __all__.append(name)
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    names = set(__all__)
    for module in _UPSTREAM_MODULES:
        names.update(name for name in dir(module) if not name.startswith("_"))
    return sorted(names)
