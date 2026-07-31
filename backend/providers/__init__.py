"""Provider adapter registry.

An adapter is a module in this package declaring:

    PROVIDER = "kimi"                     # the accounts.provider value
    AUTH     = util.AUTH_API_KEY          # how its credential is obtained
    def poll(conn, account, token): ...   # save one snapshot

Adapters may also declare LOGIN, REFRESH, BROWSER_FLOW, CAPS, PLAN_LABEL,
EXTRA and ACCOUNT_STATE hooks.

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
_CAPS = frozenset({"heartbeat", "swap"})
_CALLABLE_HOOKS = ("LOGIN", "REFRESH", "PLAN_LABEL", "EXTRA", "ACCOUNT_STATE")


def register(mod: ModuleType) -> ModuleType:
    """Validate an adapter and add it to the registry."""
    name = getattr(mod, "PROVIDER", None)
    auth = getattr(mod, "AUTH", None)
    poll = getattr(mod, "poll", None)
    if not name or auth is None or not callable(poll):
        raise ValueError(f"{mod.__name__}: adapter needs PROVIDER, AUTH and poll()")
    if auth not in util.AUTH_KINDS:
        raise ValueError(f"{mod.__name__}: unknown AUTH {auth!r}")
    try:
        caps = frozenset(getattr(mod, "CAPS", ()))
    except TypeError as e:
        raise ValueError(f"{mod.__name__}: CAPS must be a collection") from e
    unknown_caps = caps - _CAPS
    if unknown_caps:
        raise ValueError(f"{mod.__name__}: unknown CAPS {sorted(unknown_caps)!r}")
    for attr in _CALLABLE_HOOKS:
        value = getattr(mod, attr, None)
        if value is not None and not callable(value):
            raise ValueError(f"{mod.__name__}: {attr} must be callable")
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


def login_funcs() -> dict:
    """provider -> optional login callable."""
    return {name: mod.LOGIN for name, mod in load().items()
            if callable(getattr(mod, "LOGIN", None))}


def refresh_funcs() -> dict:
    """provider -> optional token refresh callable."""
    return {name: mod.REFRESH for name, mod in load().items()
            if callable(getattr(mod, "REFRESH", None))}


def browser_flows() -> dict:
    """provider -> optional browser OAuth flow specification."""
    return {name: mod.BROWSER_FLOW for name, mod in load().items()
            if isinstance(getattr(mod, "BROWSER_FLOW", None), dict)}


def caps(provider) -> frozenset:
    """Capabilities declared by a provider, or an empty set."""
    mod = get(provider)
    return frozenset(getattr(mod, "CAPS", ())) if mod else frozenset()


def hook(provider, attr):
    """A callable adapter hook, or None when it is absent."""
    mod = get(provider)
    value = getattr(mod, attr, None) if mod else None
    return value if callable(value) else None


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
