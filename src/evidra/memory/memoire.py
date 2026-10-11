# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Mémoire d'un domaine (T3.6) : entités par triplet, vues, index.

Une entité = UNE enveloppe par triplet (première observation gardée, les
re-confirmations ne bumpent que les compteurs). `observer()` tranche :
*nouvelle arête* (triplet inédit), *confirmation* (même triplet, observation
distincte — via `envelope.confirmer`, point de contrôle I6 unique),
*idempotente* (observation déjà vue ⇒ aucun effet).

Reconstruction : `appliquer_domaine` (strict, rebuild WAL) et
`memoire_depuis_etat` (tolérant, compte les ignorés — I12).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from evidra.memory.envelope import (
    CirCore,
    Derivation,
    Envelope,
    Statut,
    cle_observation,
    confirmer,
    enveloppe_depuis_resume,
    normaliser_label,
)
from evidra.memory.index import Index

Triplet = tuple[str, str, str, str]


def id_triplet(triplet: Triplet) -> str:
    """Identifiant stable d'un triplet (déterministe inter-rebuilds)."""
    return hashlib.sha256("|".join(triplet).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Issue:
    """Décision d'ingestion mémoire pour un noyau observé."""

    sorte: str  # "nouvelle" | "confirmation" | "idempotente"
    enveloppe: Envelope
    triplet: Triplet
    observation: str


class Memoire:
    """État vivant d'un domaine : entités, observations vues, index."""

    def __init__(self, domaine: str) -> None:
        self.domaine = domaine
        self.entites: dict[Triplet, Envelope] = {}
        self.vues: set[str] = set()
        self.index = Index()

    def observer(
        self,
        noyau: CirCore,
        *,
        channel: str,
        fiabilite: float,
        horodatage: str,
        alias: Mapping[tuple[str, str], str] | None = None,
    ) -> Issue:
        """Tranche nouvelle / confirmation / idempotente (T3.6, sans E/S)."""
        table = alias if alias is not None else {}
        src = table.get(
            (self.domaine, normaliser_label(noyau.source)), normaliser_label(noyau.source)
        )
        dst = table.get(
            (self.domaine, normaliser_label(noyau.target)), normaliser_label(noyau.target)
        )
        triplet: Triplet = (self.domaine, src, noyau.relation, dst)
        observation = cle_observation(noyau, self.domaine)
        if observation in self.vues:
            return Issue("idempotente", self.entites[triplet], triplet, observation)
        candidat = Envelope(noyau, ingest_channel=channel)
        if triplet in self.entites:
            entite = self.entites[triplet]
            confirmer(entite, candidat, horodatage=horodatage)  # extraction seule : accepté (I6)
            self.vues.add(observation)
            return Issue("confirmation", entite, triplet, observation)
        entite = Envelope(
            noyau,
            status=Statut.NOUVELLE,
            confirmation_count=1,
            last_confirmed_at=horodatage,
            source_reliability=fiabilite,
            ingest_channel=channel,
            derivation=Derivation.EXTRAITE,
        )
        self.ajouter(triplet, observation, entite)
        return Issue("nouvelle", entite, triplet, observation)

    def ajouter(self, triplet: Triplet, observation: str, enveloppe: Envelope) -> None:
        """Enregistre une entité (index + triplet + vue)."""
        self.entites[triplet] = enveloppe
        self.vues.add(observation)
        cir = enveloppe.cir
        self.index.ajouter(
            id_triplet(triplet), cir.source, cir.target, cir.relation, cir.confidence
        )

    def reconstruire(self, etat: Mapping[str, Any]) -> int:
        """Replie un état WAL brut : retours `(ignorés)`, tolérant (I12)."""
        ignores = 0
        for cle, capsule in etat.items():
            try:
                self._rejouer(cle, capsule)
            except (KeyError, TypeError, ValueError, AttributeError):
                ignores += 1
        return ignores

    def _rejouer(self, cle: str, capsule: Any) -> None:
        if not isinstance(capsule, Mapping):
            raise TypeError(f"capsule illisible : {cle!r}")
        triplet = tuple(capsule["triplet"])
        if len(triplet) != 4 or not all(isinstance(p, str) for p in triplet):
            raise ValueError(f"triplet illisible : {cle!r}")
        enveloppe = enveloppe_depuis_resume(capsule["enveloppe"])
        observation = str(capsule.get("observation", cle))
        self.ajouter((triplet[0], triplet[1], triplet[2], triplet[3]), observation, enveloppe)


def appliquer_domaine(etat: dict[str, Any], enr: Any) -> None:
    """Sémantique WAL des streams domaines : dernier écrit gagne par triplet.

    Strict (lève sur malformé — la corruption d'état ne passe pas silencieuse ;
    la tolérance ligne EST dans le WAL, I12).
    """

    def _triplet(capsule: Any) -> tuple[str, str, str, str]:
        brut = tuple(capsule["triplet"])
        if len(brut) != 4 or not all(isinstance(p, str) for p in brut):
            raise ValueError(f"triplet illisible : {brut!r}")
        return (brut[0], brut[1], brut[2], brut[3])

    if enr.op in ("add_edge", "confirm"):
        triplet = _triplet(enr.donnees)
        etat[id_triplet(triplet)] = dict(enr.donnees)
    elif enr.op == "tombstone":
        etat.pop(id_triplet(_triplet(enr.donnees)), None)
    # op "drop" : aucun effet d'état (compté au reçu).


def memoire_depuis_etat(domaine: str, etat: Mapping[str, Any]) -> tuple[Memoire, int]:
    """Rebuild : `(mémoire, ignorés)` — tolérant par capsule (I12)."""
    memoire = Memoire(domaine)
    return memoire, memoire.reconstruire(etat)
