# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Worker synchrone (T3.1, patch P3) : aucun appel lourd dans le scheduler.

`analyze_batch` et chargements tournent ici avec timeout issu de la directive ;
dépassement = reçu `degrade`/`failed`, jamais de blocage P1/API (`max_cycle_ms`
ne peut pas interrompre un appel en cours). Le thread condamné continue en
tâche de fond (CPython ne tue pas les threads) — résultat ignoré.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as WorkerTimeout
from typing import Any


def lancer(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Exécute `fn` en worker, lève `WorkerTimeout` au-delà de `timeout_s`."""
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise ValueError(f"timeout invalide : {timeout_s!r}")
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidra-worker") as executeur:
        futur = executeur.submit(fn)
        try:
            return futur.result(timeout=timeout_s)
        except WorkerTimeout:
            raise WorkerTimeout(f"worker dépassé : {timeout_s}s") from None
