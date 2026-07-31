"""Provider adapter registry.

An adapter is a module in this package declaring:

    PROVIDER = "kimi"                     # the accounts.provider value
    AUTH     = util.AUTH_API_KEY          # how its credential is obtained
    def poll(conn, account, token): ...   # save one snapshot

Adapters exist so that adding a subscription is one new file rather than
edits to oauth, poller, the limit_snapshots schema, status and
window_history. They report quota through util.snapshot(), whose windows the
display and history layers read straight out of raw_json.

Discovery is best-effort by design: a vendor adapter that fails to import
must not stop the daemon from polling every other account, so load() records
the failure and moves on.
"""
from __future__ import annotations
import importlib, pkgutil
from types import ModuleType

from . import util

_adapters: dict[str, ModuleType] | None = None
_errors: dict[str, str] = {}

# Modules in this package that are support code, not adapters.
_SKIP = {"util"}


def register(mod: ModuleType) -> ModuleType:
    """Validate an adapter and add it to the registry."""
    name = getattr(mod, "PROVIDER", None)
    auth = getattr(mod, "AUTH", None)
    poll = getattr(mod, "poll", None)
    if not name or auth is None or not callable(poll):
        raise ValueError(f"{mod.__name__}: adapter needs PROVIDER, AUTH and poll()")
    if auth not in util.AUTH_KINDS:
        raise ValueError(f"{mod.__name__}: unknown AUTH {auth!r}")
    load()[name] = mod
    return mod


def load() -> dict[str, ModuleType]:
    """The registry, discovering adapter modules on first use."""
    global _adapters
    if _adapters is not None:
        return _adapters
    _adapters = {}
    _errors.clear()
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name in _SKIP:
            continue
        try:
            register(importlib.import_module(f"{__name__}.{info.name}"))
        except Exception as e:              # one bad adapter, not a dead daemon
            _errors[info.name] = str(e)
            print(f"  provider adapter {info.name} failed to load: {e}")
    return _adapters


def reset_cache() -> None:
    """Drop the registry so the next call rediscovers. For tests."""
    global _adapters
    _adapters = None
    _errors.clear()


def names() -> list[str]:
    return sorted(load())


def errors() -> dict[str, str]:
    """Adapters that failed to import, name -> message."""
    load()
    return dict(_errors)


def get(provider) -> ModuleType | None:
    return load().get(provider)


def pollers() -> dict:
    """provider -> poll callable, for merging into poller.POLLERS."""
    return {name: mod.poll for name, mod in load().items()}


def auth_kind(provider) -> str | None:
    mod = get(provider)
    return getattr(mod, "AUTH", None) if mod else None


def requires_token(provider) -> bool:
    """Whether a missing tokens row should fail the poll.

    True for anything not registered here, which keeps every legacy poller on
    its original token gate.
    """
    auth = auth_kind(provider)
    return auth is None or auth not in util.TOKENLESS
