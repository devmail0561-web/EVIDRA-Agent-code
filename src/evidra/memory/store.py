# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Domaines et façade Store (T2.4) : un graphe par domaine, routage confiné.

Clés de stream `domains/<d>[/<sous>]` et `registry/<nom>`, construites
uniquement via `sous_dossier()` (ADR-0011) : une requête du domaine A ne
touche jamais les structures de B (compteurs d'accès + isolation
fonctionnelle). Création à la demande. Un seul verrou `sa.lock` à la racine
(partagé par tous les WAL du magasin — une seule instance).

`snapshot(stream)` replie via re-chargement (état reconstruit + compaction),
avec la fonction `appliquer` enregistrée par flux (fail-closed sinon).
`lookup` scanne le WAL (O(n) honnête — T2.5 l'indexe, preuve d'équivalence).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from evidra.kernel.contracts import Record
from evidra.memory.snapshot import (
    Chargement,
    charger,
    compacter,
    sous_dossier,
)
from evidra.memory.wal import WAL, Enregistrement, WALError

RACINES = ("domains", "registry")

Appliquer = Callable[[dict[str, Any], Enregistrement], None]


class StoreError(Exception):
    """Clé de stream invalide, appliquer manquant, etc. (fail-closed)."""


class Magasin:
    """Implémente le Protocol `Store` : multiplexeur de streams persistés."""

    def __init__(self, racine: Path) -> None:
        self._racine = racine
        racine.mkdir(parents=True, exist_ok=True)
        self._verrou = FileLock(str(racine / "sa.lock"))
        try:
            self._verrou.acquire(timeout=0.0)
        except Timeout:
            raise StoreError(f"racine verrouillée (deux instances ?) : {racine}") from None
        self._journaux: dict[str, WAL] = {}
        self._appliquers: dict[str, Appliquer] = {}
        self._etats: dict[str, dict[str, Any]] = {}
        self._acces: dict[str, int] = {}

    def close(self) -> None:
        """Flush + fsync de tous les streams, libération du verrou."""
        try:
            for journal in self._journaux.values():
                journal.sync()
        finally:
            for journal in self._journaux.values():
                journal.close()
            self._journaux.clear()
            self._verrou.release()

    def __enter__(self) -> Magasin:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def flux(self, cle: str) -> WAL:
        """WAL du stream, créé à la demande (dossier confiné)."""
        journal = self._journaux.get(cle)
        if journal is None:
            try:
                dossier = sous_dossier(self._racine, *self._parties(cle))
            except ValueError as exc:
                raise StoreError(str(exc)) from None
            dossier.mkdir(parents=True, exist_ok=True)
            try:
                journal = WAL(dossier / "wal.jsonl", verrouiller=False)
            except WALError as exc:
                raise StoreError(str(exc)) from None
            self._journaux[cle] = journal
        return journal

    def definir_appliquer(self, cle: str, appliquer: Appliquer) -> None:
        """Enregistre la sémantique d'application d'un stream (avant snapshot)."""
        self._parties(cle)
        self._appliquers[cle] = appliquer

    def append(self, stream: str, record: Record) -> int:
        """Ajoute au stream, retourne le `seq` (Protocol `Store`)."""
        self._acces[stream] = self._acces.get(stream, 0) + 1
        return self.flux(stream).append(record.op, record.key, record.data)

    def lookup(self, stream: str, key: str) -> Record | None:
        """Dernier enregistrement pour `key` : WAL d'abord, snapshot sinon.

        Le WAL est autoritaire ; le cache snapshot ne comble que les clés
        absentes du WAL (`op="snapshot"`, pliée). Un `tombstone` en WAL
        masque toujours l'état snapshotté.
        """
        self._acces[stream] = self._acces.get(stream, 0) + 1
        if stream not in self._etats:
            appliquer = self._appliquers.get(stream)
            if appliquer is not None:
                self._etats[stream] = charger(
                    self._dossier(stream), self.flux(stream), appliquer=appliquer
                ).etat
        for enr in reversed(self.flux(stream).relire().valides):
            if enr.cle == key:
                if enr.op == "tombstone":
                    return None
                return Record(stream=stream, op=enr.op, key=enr.cle, data=dict(enr.donnees))
        snapshot = self._etats.get(stream, {}).get(key)
        if snapshot is None:
            return None
        return Record(stream=stream, op="snapshot", key=key, data=dict(snapshot))

    def snapshot(self, stream: str) -> None:
        """Compaction explicite : rebuild + repli (appliquer requis)."""
        self._acces[stream] = self._acces.get(stream, 0) + 1
        appliquer = self._appliquers.get(stream)
        if appliquer is None:
            raise StoreError(f"snapshot sans appliquer enregistré : {stream!r}")
        charge = charger(self._dossier(stream), self.flux(stream), appliquer=appliquer)
        compacter(self._dossier(stream), self.flux(stream), charge.etat, charge.last_seq)
        self._etats[stream] = charge.etat

    def recharger(self, cle: str) -> Chargement:
        """Recharge un stream (démarrage, T4.5) avec son appliquer."""
        self._acces[cle] = self._acces.get(cle, 0) + 1
        appliquer = self._appliquers.get(cle)
        if appliquer is None:
            raise StoreError(f"rechargement sans appliquer enregistré : {cle!r}")
        charge = charger(self._dossier(cle), self.flux(cle), appliquer=appliquer)
        self._etats[cle] = charge.etat
        return charge

    def acces(self, cle: str) -> int:
        """Compteur d'accès au stream (preuve d'isolation)."""
        return self._acces.get(cle, 0)

    def _dossier(self, cle: str) -> Path:
        try:
            return sous_dossier(self._racine, *self._parties(cle))
        except ValueError as exc:
            raise StoreError(str(exc)) from None

    @staticmethod
    def _parties(cle: str) -> tuple[str, ...]:
        parties = tuple(cle.split("/"))
        if len(parties) < 2 or len(parties) > 3 or parties[0] not in RACINES:
            raise StoreError(
                f"clé de stream invalide : {cle!r} (domains/<d>[/<sous>] ou registry/<nom>)"
            )
        return parties
