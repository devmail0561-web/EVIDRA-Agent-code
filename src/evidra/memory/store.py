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

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from evidra.kernel.contracts import Record
from evidra.memory.memoire import Memoire, appliquer_domaine, memoire_depuis_etat
from evidra.memory.snapshot import (
    Chargement,
    charger,
    compacter,
    sous_dossier,
)
from evidra.memory.wal import WAL, Enregistrement, WALError

RACINES = ("domains", "registry")

Appliquer = Callable[[dict[str, Any], Enregistrement], None]


def parties_cle(cle: str) -> tuple[str, ...]:
    """Valide une clé de stream, retourne ses parties (fail-closed)."""
    parties = tuple(cle.split("/"))
    if len(parties) < 2 or len(parties) > 3 or parties[0] not in RACINES:
        raise StoreError(
            f"clé de stream invalide : {cle!r} (domains/<d>[/<sous>] ou registry/<nom>)"
        )
    return parties


def inventorier_racine(racine: Path) -> list[str]:
    """Clés des streams valides sur disque, sans verrou (CLI + Magasin)."""
    cles = []
    for chemin in sorted(racine.rglob("wal.jsonl")):
        try:
            cle = str(chemin.parent.relative_to(racine)).replace("\\", "/")
            parties_cle(cle)
        except (StoreError, ValueError):
            continue
        cles.append(cle)
    return cles


def reperer_invalides(racine: Path) -> list[str]:
    """Dossiers `wal.jsonl` hors clés valides (diagnostic `/status`, sans verrou)."""
    valides = set(inventorier_racine(racine))
    invalides = []
    for chemin in sorted(racine.rglob("wal.jsonl")):
        try:
            cle = str(chemin.parent.relative_to(racine)).replace("\\", "/")
        except ValueError:
            continue
        if cle not in valides:
            invalides.append(cle)
    return invalides


def etat_racine(racine: Path) -> dict[str, Any]:
    """État d'un `data_dir` (CLI `status`, API `/status`) : manifeste + streams.

    Lecture seule, sans verrou, tolérante (I12) : manifeste corrompu ⇒ `{}`
    + avertissement, jamais levée.
    """
    manifeste: dict[str, Any] = {}
    avertissements: list[str] = []
    chemin_manifeste = racine / "sa_manifest.json"
    if chemin_manifeste.exists():
        try:
            brut = json.loads(chemin_manifeste.read_text(encoding="utf-8"))
            if isinstance(brut, dict):
                manifeste = brut
            else:
                avertissements.append("manifeste non-objet, ignoré")
        except ValueError:
            avertissements.append("manifeste illisible, ignoré")
    streams = []
    for cle in inventorier_racine(racine):
        dossier = racine.joinpath(*cle.split("/"))
        with WAL(dossier / "wal.jsonl", verrouiller=False) as journal:
            charge = charger(dossier, journal, appliquer=appliquer_domaine, stream=cle)
        streams.append(charge.rapport.en_dict() if charge.rapport is not None else {"stream": cle})
    invalides = sorted(reperer_invalides(racine))
    if invalides:
        avertissements.append(f"{len(invalides)} stream(s) hors clés : {invalides}")
    return {
        "manifeste": manifeste,
        "streams": streams,
        "invalides": invalides,
        "avertissements": avertissements,
    }


def lire_domaine(
    racine: Path,
    domaine: str,
    seuils: tuple[float, float] | None = None,
    n_confirmee: int | None = None,
    limite_repli: int | None = None,
) -> tuple[Memoire, int]:
    """Lecture seule d'un domaine, sans verrou (CLI `query`).

    Même pipeline que `Magasin.recharger` (snapshot + rejeu WAL +
    `memoire_depuis_etat`), sans prendre `sa.lock` : utilisable pendant
    que l'agent tourne. Seuils = directive (`None` ⇒ défauts du schéma).
    Domaine inconnu ⇒ `StoreError`.
    """
    dossier = racine / "domains" / domaine
    if not dossier.is_dir():
        raise StoreError(f"domaine inconnu : {domaine}")
    cle = f"domains/{domaine}"
    with WAL(dossier / "wal.jsonl", verrouiller=False) as journal:
        charge = charger(dossier, journal, appliquer=appliquer_domaine, stream=cle)
    return memoire_depuis_etat(domaine, charge.etat, seuils, n_confirmee, limite_repli)


class StoreError(Exception):
    """Clé de stream invalide, appliquer manquant, etc. (fail-closed)."""


class Magasin:
    """Implémente le Protocol `Store` : multiplexeur de streams persistés."""

    def __init__(
        self,
        racine: Path,
        *,
        batch_lignes: int | None = None,
        batch_ms: float | None = None,
    ) -> None:
        """`batch_*=None` ⇒ défauts canoniques de la directive (`Budgets.fsync_*`, I9).

        Le démarrage (`demarrage`) passe les valeurs effectives ; les CLI
        ponctuels et les tests s'en remettent au canonique.
        """
        self._racine = racine
        self._batch_lignes = batch_lignes
        self._batch_ms = batch_ms
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
        self._derniers_seq: dict[str, int] = {}

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
                journal = WAL(
                    dossier / "wal.jsonl",
                    verrouiller=False,
                    batch_lignes=self._batch_lignes,
                    batch_ms=self._batch_ms,
                )
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
        seq = self.flux(stream).append(record.op, record.key, record.data)
        self._derniers_seq[stream] = seq
        return seq

    def _appliquer_pour(self, cle: str) -> Appliquer | None:
        """Appliquer enregistré, sinon sémantique domaine par défaut (T3.6)."""
        appliquer = self._appliquers.get(cle)
        if appliquer is None and cle.startswith("domains/"):
            appliquer = appliquer_domaine
        return appliquer

    def lookup(self, stream: str, key: str) -> Record | None:
        """Dernier enregistrement pour `key` : WAL d'abord, snapshot sinon.

        Le WAL est autoritaire ; le cache snapshot ne comble que les clés
        absentes du WAL (`op="snapshot"`, pliée). Un `tombstone` en WAL
        masque toujours l'état snapshotté.
        """
        self._acces[stream] = self._acces.get(stream, 0) + 1
        if stream not in self._etats:
            appliquer = self._appliquer_pour(stream)
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
        appliquer = self._appliquer_pour(stream)
        if appliquer is None:
            raise StoreError(f"snapshot sans appliquer enregistré : {stream!r}")
        charge = charger(self._dossier(stream), self.flux(stream), appliquer=appliquer)
        compacter(self._dossier(stream), self.flux(stream), charge.etat, charge.last_seq)
        self._etats[stream] = charge.etat

    def recharger(self, cle: str) -> Chargement:
        """Recharge un stream (démarrage, T4.5) avec son appliquer."""
        self._acces[cle] = self._acces.get(cle, 0) + 1
        appliquer = self._appliquer_pour(cle)
        if appliquer is None:
            raise StoreError(f"rechargement sans appliquer enregistré : {cle!r}")
        charge = charger(self._dossier(cle), self.flux(cle), appliquer=appliquer)
        self._etats[cle] = charge.etat
        return charge

    def acces(self, cle: str) -> int:
        """Compteur d'accès au stream (preuve d'isolation)."""
        return self._acces.get(cle, 0)

    def derniers_seq(self) -> dict[str, int]:
        """Derniers `seq` écrits par stream (cette instance, pour `/status`)."""
        return dict(self._derniers_seq)

    def synchroniser(self) -> None:
        """Flush + fsync des streams ouverts, sans fermer (point de reprise)."""
        for journal in self._journaux.values():
            journal.sync()

    def inventorier(self) -> list[str]:
        """Clés des streams présents sur disque (valides uniquement)."""
        return inventorier_racine(self._racine)

    def _dossier(self, cle: str) -> Path:
        try:
            return sous_dossier(self._racine, *self._parties(cle))
        except ValueError as exc:
            raise StoreError(str(exc)) from None

    @staticmethod
    def _parties(cle: str) -> tuple[str, ...]:
        return parties_cle(cle)
