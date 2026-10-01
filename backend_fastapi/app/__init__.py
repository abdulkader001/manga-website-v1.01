"""Manga reader backend.

Before anything else in the package runs, Secret Vault values (admin-panel
settings) are copied into the environment, so every module -- including ones
that read their configuration once at import -- sees them like ``.env``
values. See ``vault_preload``.
"""

from .vault_preload import preload_once as _preload_vault

_preload_vault()
