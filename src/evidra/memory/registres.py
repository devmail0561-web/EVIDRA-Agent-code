# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Registres (T2.6) : sources, alias, modèles, tâches, alertes — 5 streams WAL.

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
FLUX_ALERTES = "registry/alertes"


class EtatTache(StrEnum):
    """États d'une tâche persistée (§13.4, §26.2)."""

    ATTENTE = "pending"
    COURS = "running"
    TERMINEE = "done"
    ABANDONNEE = "abandoned"


def _appliquer_dict(etat: dict[str, Any], enr: Enregistrement) -> None:
    """Upsert générique (`tombstone` = retrait) pour les 5 registres."""
    if enr.op in ("receipt", "drop"):
        return  # audit seul, aucun effet d'état (patch P1)
    if enr.op == "tombstone":
        etat.pop(enr.cle, None)
    else:
        etat[enr.cle] = dict(enr.donnees)


class Registres:
    """Façade typée sur les 5 streams de registres d'un magasin."""

    def __init__(self, magasin: Magasin) -> None:
        self._magasin = magasin
        for flux in (FLUX_SOURCES, FLUX_ALIAS, FLUX_MODELES, FLUX_TACHES, FLUX_ALERTES):
            magasin.definir_appliquer(flux, _appliquer_dict)

    def noter_source(self, uri: str, champs: Mapping[str, Any]) -> int:
        """Upsert des compteurs d'une source (calculés en T6.3)."""
        return self._magasin.append(
            FLUX_SOURCES, Record(stream=FLUX_SOURCES, op="put", key=uri, data=dict(champs))
        )

    def noter_compteurs(self, uri: str, compteurs: Mapping[str, Any]) -> int:
        """Compteurs calculés d'une source (T6.3, jamais à la main)."""
        return self.noter_source(uri, {"compteurs": dict(compteurs)})

    def compteurs(self, uri: str) -> dict[str, Any]:
        """Compteurs stockés d'une source, `{}` si inconnue (T6.3)."""
        fiche = self.source(uri)
        if not isinstance(fiche, dict):
            return {}
        compteurs = fiche.get("compteurs")
        return dict(compteurs) if isinstance(compteurs, dict) else {}

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

    def creer_tache(
        self,
        ident: str,
        type_tache: str,
        budget: float,
        deadline: str,
        extras: Mapping[str, Any] | None = None,
    ) -> int:
        """Crée une tâche `pending` (budget et deadline opaques ici).

        `extras` : charge informative (question, chaîne…) lue par le
        consommateur futur, ignorée par les consommateurs actuels.
        """
        donnees: dict[str, Any] = {
            "id": ident,
            "type": type_tache,
            "budget": budget,
            "consomme_ms": 0.0,
            "consomme_appels": 0,
            "deadline": deadline,
            "etat": EtatTache.ATTENTE.value,
            "motif": "",
        }
        if extras:
            donnees.update({k: v for k, v in extras.items() if k not in donnees})
        return self._magasin.append(
            FLUX_TACHES,
            Record(
                stream=FLUX_TACHES,
                op="put",
                key=f"task:{ident}",
                data=donnees,
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

    def noter_conso(self, ident: str, ms: float, appels: int) -> None:
        """Cumule le coût mesuré d'une exécution (suivi conso, T5.9)."""
        fiche = self.tache(ident)
        if fiche is None:
            raise ValueError(f"tâche inconnue : {ident!r}")
        fiche["consomme_ms"] = float(fiche.get("consomme_ms", 0.0)) + ms
        fiche["consomme_appels"] = int(fiche.get("consomme_appels", 0)) + appels
        self._magasin.append(
            FLUX_TACHES, Record(stream=FLUX_TACHES, op="conso", key=f"task:{ident}", data=fiche)
        )

    def relever_expiration(self, maintenant_iso: str) -> list[str]:
        """Marque `abandoned` (motivé) les tâches dépassées non terminées.

        Tolérant (I12) : horloge ou deadline illisible (naive/aware mélangés
        inclus) ⇒ tâche ignorée, jamais de levée vers le tick.
        """
        try:
            maintenant = datetime.fromisoformat(maintenant_iso)
        except (TypeError, ValueError):
            return []
        abandonnees: list[str] = []
        etat = self._magasin.recharger(FLUX_TACHES).etat
        for cle, fiche in sorted(etat.items()):
            if not cle.startswith("task:") or not isinstance(fiche, dict):
                continue
            if fiche.get("etat") in (EtatTache.TERMINEE.value, EtatTache.ABANDONNEE.value):
                continue
            try:
                echeance = datetime.fromisoformat(str(fiche.get("deadline", "")))
                compare = echeance < maintenant
            except (TypeError, ValueError):
                continue
            if compare:
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

    def lever_alerte(self, cle: str, fiche: Mapping[str, Any]) -> int:
        """Lève une alerte (`active`, T7.2) ; réémission gérée par l'appelant."""
        donnees = dict(fiche)
        donnees["etat"] = "active"
        return self._magasin.append(
            FLUX_ALERTES, Record(stream=FLUX_ALERTES, op="lever", key=cle, data=donnees)
        )

    def noter_envoi(self, cle: str, horodatage: str) -> int:
        """Horodate le dernier envoi d'une alerte (fenêtre dédup, T7.2)."""
        return self._magasin.append(
            FLUX_ALERTES,
            Record(stream=FLUX_ALERTES, op="envoi", key=f"envoi:{cle}", data={"a": horodatage}),
        )

    def acquitter_alerte(self, cle: str, *, motif: str) -> int:
        """Acquitte une alerte active (motif exigé, persisté)."""
        if not motif or not motif.strip():
            raise ValueError("acquittement sans motif refusé")
        fiche = self.alerte(cle)
        if fiche is None:
            raise ValueError(f"alerte inconnue : {cle!r}")
        donnees = dict(fiche)
        donnees["etat"] = "acquittee"
        donnees["motif_acquittement"] = motif
        return self._magasin.append(
            FLUX_ALERTES, Record(stream=FLUX_ALERTES, op="acquitter", key=cle, data=donnees)
        )

    def alerte(self, cle: str) -> dict[str, Any] | None:
        """Fiche alerte, `None` si inconnue."""
        trouve = self._magasin.lookup(FLUX_ALERTES, cle)
        return dict(trouve.data) if trouve is not None else None

    def alertes_actives(self) -> dict[str, dict[str, Any]]:
        """Alertes `active` non acquittées (P1, T7.2)."""
        etat = self._magasin.recharger(FLUX_ALERTES).etat
        return {
            cle: fiche
            for cle, fiche in etat.items()
            if isinstance(fiche, dict)
            and not cle.startswith("envoi:")
            and fiche.get("etat") == "active"
        }

    def dernier_envoi(self, cle: str) -> str | None:
        """Dernier envoi horodaté d'une alerte, `None` si jamais émise."""
        trouve = self._magasin.lookup(FLUX_ALERTES, f"envoi:{cle}")
        if trouve is None:
            return None
        horodatage = trouve.data.get("a")
        return horodatage if isinstance(horodatage, str) else None
