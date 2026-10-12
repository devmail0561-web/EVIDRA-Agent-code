# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Registres (T2.6) : sources, alias, modèles, tâches — 4 streams WAL.

Même code WAL (un seul mécanisme prouvé) ; rejeu tolérant par ligne hérité.
`tâches` : `id`, `type`, `budget`, `deadline`, `état` ; expiration ⇒
`abandoned` avec motif (jamais supprimée). Curseurs d'adaptateurs stockés
comme enregistrements d'op `cursor` dans `tasks`. `modèles` :
`{hash, chemin, version_moteur, statut}` — aucun modèle n'est CONSOMMÉ tant
que B2 n'est pas levé (gate T10.6) ; le registre ne fait que consigner.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from evidra.kernel.contracts import Record
from evidra.memory.store import Magasin
from evidra.memory.wal import Enregistrement

FLUX_SOURCES = "registry/sources"
FLUX_ALIAS = "registry/aliases"
FLUX_MODELES = "registry/models"
FLUX_TACHES = "registry/tasks"


class EtatTache(StrEnum):
    """États d'une tâche persistée (§13.4, §26.2)."""

    ATTENTE = "pending"
    COURS = "running"
    TERMINEE = "done"
    ABANDONNEE = "abandoned"


def _appliquer_dict(etat: dict[str, Any], enr: Enregistrement) -> None:
    """Upsert générique (`tombstone` = retrait) pour les 4 registres."""
    if enr.op in ("receipt", "drop"):
        return  # audit seul, aucun effet d'état (patch P1)
    if enr.op == "tombstone":
        etat.pop(enr.cle, None)
    else:
        etat[enr.cle] = dict(enr.donnees)


class Registres:
    """Façade typée sur les 4 streams de registres d'un magasin."""

    def __init__(self, magasin: Magasin) -> None:
        self._magasin = magasin
        for flux in (FLUX_SOURCES, FLUX_ALIAS, FLUX_MODELES, FLUX_TACHES):
            magasin.definir_appliquer(flux, _appliquer_dict)

    def noter_source(self, uri: str, champs: Mapping[str, Any]) -> int:
        """Upsert des compteurs d'une source (calculés en T6.3)."""
        return self._magasin.append(
            FLUX_SOURCES, Record(stream=FLUX_SOURCES, op="put", key=uri, data=dict(champs))
        )

    def source(self, uri: str) -> dict[str, Any] | None:
        """Fiche source, `None` si inconnue."""
        trouve = self._magasin.lookup(FLUX_SOURCES, uri)
        return dict(trouve.data) if trouve is not None else None

    def definir_alias(self, domaine: str, canonique: str, variantes: list[str]) -> int:
        """Table d'alias par domaine (promotion humaine en T6.5)."""
        return self._magasin.append(
            FLUX_ALIAS,
            Record(
                stream=FLUX_ALIAS,
                op="put",
                key=f"{domaine}:{canonique}",
                data={"variantes": list(variantes)},
            ),
        )

    def alias(self, domaine: str, canonique: str) -> list[str]:
        """Variantes connues, `[]` si aucune."""
        trouve = self._magasin.lookup(FLUX_ALIAS, f"{domaine}:{canonique}")
        if trouve is None:
            return []
        variantes = trouve.data.get("variantes")
        return list(variantes) if isinstance(variantes, list) else []

    def noter_modele(self, hash_modele: str, champs: Mapping[str, Any]) -> int:
        """Consigne un modèle (`hash, chemin, version_moteur, statut`) — sans le charger."""
        return self._magasin.append(
            FLUX_MODELES, Record(stream=FLUX_MODELES, op="put", key=hash_modele, data=dict(champs))
        )

    def modeles(self) -> dict[str, Any]:
        """Tous les modèles consignés (vide tant que B2 n'est pas levé)."""
        return self._magasin.recharger(FLUX_MODELES).etat

    def creer_tache(self, ident: str, type_tache: str, budget: float, deadline: str) -> int:
        """Crée une tâche `pending` (budget et deadline opaques ici)."""
        return self._magasin.append(
            FLUX_TACHES,
            Record(
                stream=FLUX_TACHES,
                op="put",
                key=f"task:{ident}",
                data={
                    "id": ident,
                    "type": type_tache,
                    "budget": budget,
                    "deadline": deadline,
                    "etat": EtatTache.ATTENTE.value,
                    "motif": "",
                },
            ),
        )

    def taches(self) -> dict[str, Any]:
        """Toutes les entrées du stream tâches (tâches + curseurs)."""
        return self._magasin.recharger(FLUX_TACHES).etat

    def passer_etat(self, ident: str, etat: EtatTache, motif: str = "") -> int:
        """Transition d'état (motif exigé pour `abandoned`)."""
        if etat is EtatTache.ABANDONNEE and not motif:
            raise ValueError("abandon sans motif refusé")
        fiche = self.tache(ident)
        if fiche is None:
            raise ValueError(f"tâche inconnue : {ident!r}")
        fiche["etat"] = etat.value
        fiche["motif"] = motif
        return self._magasin.append(
            FLUX_TACHES, Record(stream=FLUX_TACHES, op="etat", key=f"task:{ident}", data=fiche)
        )

    def tache(self, ident: str) -> dict[str, Any] | None:
        """Fiche tâche, `None` si inconnue."""
        trouve = self._magasin.lookup(FLUX_TACHES, f"task:{ident}")
        return dict(trouve.data) if trouve is not None else None

    def relever_expiration(self, maintenant_iso: str) -> list[str]:
        """Marque `abandoned` (motivé) les tâches dépassées non terminées."""
        maintenant = datetime.fromisoformat(maintenant_iso)
        abandonnees: list[str] = []
        etat = self._magasin.recharger(FLUX_TACHES).etat
        for cle, fiche in sorted(etat.items()):
            if not cle.startswith("task:") or not isinstance(fiche, dict):
                continue
            if fiche.get("etat") in (EtatTache.TERMINEE.value, EtatTache.ABANDONNEE.value):
                continue
            try:
                echeance = datetime.fromisoformat(str(fiche.get("deadline", "")))
            except ValueError:
                continue
            if echeance < maintenant:
                self.passer_etat(str(fiche["id"]), EtatTache.ABANDONNEE, motif="deadline dépassée")
                abandonnees.append(str(fiche["id"]))
        return abandonnees

    def noter_curseur(self, adaptateur: str, curseur: str) -> int:
        """Persiste un curseur d'adaptateur (jamais à côté des sources)."""
        return self._magasin.append(
            FLUX_TACHES,
            Record(
                stream=FLUX_TACHES,
                op="cursor",
                key=f"cursor:{adaptateur}",
                data={"curseur": curseur},
            ),
        )

    def curseur(self, adaptateur: str) -> str | None:
        """Curseur persisté, `None` si aucun."""
        trouve = self._magasin.lookup(FLUX_TACHES, f"cursor:{adaptateur}")
        if trouve is None:
            return None
        curseur = trouve.data.get("curseur")
        return curseur if isinstance(curseur, str) else None
