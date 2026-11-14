"""Small in-process LRU result cache. Keys always include the dataset revision."""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any, Callable

_MAX = 256
_lock = threading.Lock()
_store: "OrderedDict[str, Any]" = OrderedDict()
stats = {"hits": 0, "misses": 0, "invalidations": 0}
_listeners: list[Callable[[], None]] = []  # other in-process caches cleared together with this one (v1.2)


def make_key(name: str, revision: int, params: dict) -> str:
    return f"{name}|rev={revision}|" + json.dumps(params, sort_keys=True, default=str)


def get_or_compute(key: str, fn: Callable[[], Any]) -> Any:
    with _lock:
        if key in _store:
            _store.move_to_end(key)
            stats["hits"] += 1
            return _store[key]
    value = fn()
    with _lock:
        stats["misses"] += 1
        _store[key] = value
        while len(_store) > _MAX:
            _store.popitem(last=False)
    return value


def invalidate() -> None:
    with _lock:
        _store.clear()
        stats["invalidations"] += 1
    for fn in list(_listeners):
        fn()
