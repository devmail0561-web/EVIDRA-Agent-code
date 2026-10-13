# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Scheduler squelette (T1.5, noyau stdlib) : boucle mono-thread, 6 niveaux.

Le noyau ne nomme aucun outil : les niveaux reçoivent des (condition, effet)
fournis. Un seul effet principal par niveau actif, séquentiel, reçu lu avant
la suite. Budgets par cycle avec dépassement tracé `budget:` ; anti-famine :
P4–P6 gardent `reserve_fond` appels même si P1–P3 saturent. Aucun appel lourd
ici (timeouts dans les workers, §13.5) : `max_cycle_ms` dépassé = on ne
démarre plus d'effet, tracé.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from enum import IntEnum

from evidra.kernel.contracts import Status, ToolResult, Verb

Priorite = IntEnum("Priorite", {"P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5, "P6": 6})
# Niveaux 1–6 (§1.3 de l'étude), 1 = le plus prioritaire.


_HAUTS = frozenset({Priorite.P1, Priorite.P2, Priorite.P3})


@dataclass(frozen=True, slots=True)
class Budgets:
    """Budgets par cycle (`None` = illimité, sauf `max_tool_calls`)."""

    max_tool_calls: int = 6
    max_ingest_per_cycle: int | None = None
    max_cycle_ms: float | None = None
    max_wal_bytes: int | None = None
    reserve_fond: int = 1


@dataclass(frozen=True, slots=True)
class Recu:
    """Reçu lu avant de continuer : niveau + résultat."""

    niveau: Priorite
    resultat: ToolResult


@dataclass(frozen=True, slots=True)
class RapportTick:
    """Bilan d'un tick : reçus dans l'ordre, dépassements, durée."""

    tick: int
    recus: tuple[Recu, ...]
    budgets_depasse: tuple[str, ...]
    duree_ms: float


# (condition, effet, verbe, poids WAL) — tuple interne, jamais exposé.
_Prog = tuple[Callable[[], bool], Callable[[], ToolResult], Verb, int]
# (niveau, effet, verbe, poids WAL, futur) — file d'événements thread-safe.
_Entree = tuple[Priorite, Callable[[], ToolResult], Verb, int, "Future[ToolResult] | None"]


class Scheduler:
    """Boucle mono-thread (ADR-0003 : single-writer)."""

    def __init__(self, budgets: Budgets | None = None) -> None:
        self._budgets = budgets if budgets is not None else Budgets()
        self._actions: dict[Priorite, list[_Prog]] = {n: [] for n in Priorite}
        self._file: queue.Queue[_Entree] = queue.Queue()
        self.tick = 0

    def configurer_budgets(self, budgets: Budgets) -> None:
        self._budgets = budgets

    def enregistrer(
        self,
        niveau: Priorite,
        condition: Callable[[], bool],
        effet: Callable[[], ToolResult],
        *,
        verbe: Verb = Verb.READ,
        wal_bytes: int = 0,
    ) -> None:
        """Enregistre (condition, effet) ; premier vrai gagne par niveau."""
        self._actions[niveau].append((condition, effet, verbe, wal_bytes))

    def deposer(
        self,
        niveau: Priorite,
        effet: Callable[[], ToolResult],
        *,
        verbe: Verb = Verb.READ,
        wal_bytes: int = 0,
    ) -> Future[ToolResult]:
        """Dépose un événement (file thread-safe) ; réveil au tick."""
        futur: Future[ToolResult] = Future()
        self._file.put((niveau, effet, verbe, wal_bytes, futur))
        return futur

    def tour(self, delai: float = 0.0) -> RapportTick:
        """Un tick : drenner, évaluer P1–P6, exécuter séquentiel, reçus."""
        debut = time.monotonic()
        recus, depasses = self._executer(self._planifier(self._drenner(delai)), debut)
        self.tick += 1
        duree = (time.monotonic() - debut) * 1000.0
        return RapportTick(self.tick, tuple(recus), tuple(depasses), duree)

    def boucler(self, arret: threading.Event, delai: float = 0.05) -> None:
        """Boucle jusqu'au signal (arrêt propre : plus aucun tick après).

        Repli générique du noyau (stdlib, sans directive) : le SA passe
        toujours sa valeur (`Boucle` ← `Budgets.attente_boucle_s`, I9).
        """
        while not arret.is_set():
            self.tour(delai)

    def _drenner(self, delai: float) -> dict[Priorite, list[_Entree]]:
        uniques: dict[Priorite, list[_Entree]] = {n: [] for n in Priorite}
        while True:
            try:
                attente = self._file.get(timeout=delai)
            except queue.Empty:
                return uniques
            uniques[attente[0]].append(attente)
            delai = 0.0

    def _planifier(self, uniques: dict[Priorite, list[_Entree]]) -> list[_Entree]:
        plan: list[_Entree] = []
        for niveau in Priorite:
            file = uniques[niveau]
            if file:
                for attente in file[1:]:
                    self._file.put(attente)
                att = file[0]
                plan.append((niveau, att[1], att[2], att[3], att[4]))
                continue
            for condition, effet, verbe, poids in self._actions[niveau]:
                if condition():
                    plan.append((niveau, effet, verbe, poids, None))
                    break
        return plan

    def _executer(self, plan: list[_Entree], debut: float) -> tuple[list[Recu], list[str]]:
        b = self._budgets
        recus: list[Recu] = []
        dep: list[str] = []
        fond = sum(1 for p in plan if p[0] not in _HAUTS)
        quota = max(0, b.max_tool_calls - min(b.reserve_fond, fond))
        appels = ingeres = octets = 0
        for niveau, effet, verbe, poids, futur in plan:
            if appels >= b.max_tool_calls or (niveau in _HAUTS and appels >= quota):
                dep.append("budget:max_tool_calls")
                continue
            if b.max_cycle_ms is not None and (time.monotonic() - debut) * 1000.0 > b.max_cycle_ms:
                dep.append("budget:max_cycle_ms")
                break
            limite = b.max_ingest_per_cycle
            if verbe is Verb.INGEST and limite is not None and ingeres >= limite:
                dep.append("budget:max_ingest_per_cycle")
                continue
            if b.max_wal_bytes is not None and octets + poids > b.max_wal_bytes:
                dep.append("budget:max_wal_bytes")
                continue
            try:
                resultat = effet()
            except Exception as exc:  # noqa: BLE001 — un effet ne doit jamais lever
                resultat = ToolResult(status=Status.FAILED, payload={"motif": f"panne : {exc}"})
            appels += 1
            ingeres += verbe is Verb.INGEST  # bool <: int, compteur d'ingests
            octets += poids
            recus.append(Recu(niveau, resultat))
            if futur is not None and not futur.done():
                futur.set_result(resultat)
        saute = ToolResult(status=Status.DEGRADE, payload={"motif": "budget dépassé"})
        for entree in plan:
            if entree[4] is not None and not entree[4].done():
                entree[4].set_result(saute)
        return recus, dep
