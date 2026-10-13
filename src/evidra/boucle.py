# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Boucle agentique (T4.4) : orchestre sans toucher au noyau (gelé, I2).

Par tick : tiède (`Surveillant` → budgets + politique, reçu WAL au changement)
→ tâches P4–P6 (un consommateur par niveau, déposé en one-shot) → sélection
politique (niveaux observés) → `Scheduler.tour()` (ordre, budgets, anti-famine
natifs) → rapport. Contexte borné via `borner()` (T5.x l'utilisera).

Écritures WAL : transitions de tâches (registres), `ingest` (domaines), reçu
`directive` (gouvernance). Le reste est lecture (patch P1 : les reçus sans
mutation n'écrivent pas ; « qu'a fait le SA ? » = lecture WAL).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from evidra.directive.reload import Surveillant
from evidra.directive.schema import Surveillance
from evidra.kernel.contracts import Record, Status, ToolResult
from evidra.kernel.gate import Policy
from evidra.kernel.scheduler import Budgets, Priorite, Recu, Scheduler
from evidra.memory.registres import EtatTache, Registres
from evidra.memory.store import Magasin
from evidra.policy import TABLE, Situation, selectionner
from evidra.util import borner as borner

Effet = Callable[[], ToolResult]

_LOG = logging.getLogger(__name__)


def outils_niveau(niveau: Priorite) -> tuple[str, ...]:
    """Outils d'un niveau selon la TABLE (§1.3)."""
    for n, _, outils in TABLE:
        if n is niveau:
            return outils
    return ()


@dataclass(frozen=True, slots=True)
class RapportBoucle:
    """Bilan d'un tick : scheduler + sélection + gouvernance."""

    tick: int
    recus: tuple[Recu, ...]
    budgets_depasse: tuple[str, ...]
    selection: tuple[Priorite, ...]
    directive_changee: bool
    alertes: tuple[str, ...]


class Boucle:
    """Une boucle par domaine : le scheduler tourne, la boucle gouverne."""

    def __init__(
        self,
        *,
        domaine: str,
        ordonnanceur: Scheduler,
        magasin: Magasin,
        registres: Registres,
        outils: Mapping[str, Effet],
        surveillant: Surveillant | None = None,
        horloge: Callable[[], str] | None = None,
        alerteur: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self._domaine = domaine
        self._ordonnanceur = ordonnanceur
        self._magasin = magasin
        self._registres = registres
        self._outils = dict(outils)
        self._surveillant = surveillant
        self._horloge = horloge
        self._alerteur = alerteur
        self._alertes_max: int | None = None
        self._politique = Policy()
        self._hash_directive = surveillant.empreinte_courante() if surveillant is not None else ""
        self._actifs: set[Priorite] = set()
        self._plan: dict[Priorite, str] = {}
        self._dans_tick = False
        for niveau in Priorite:
            # `n=niveau` : lie la valeur (closure en boucle sinon).
            self._ordonnanceur.enregistrer(
                niveau, lambda n=niveau: n in self._actifs, lambda n=niveau: self._periodique(n)
            )

    @property
    def domaine(self) -> str:
        """Domaine de la boucle (exploitant CLI)."""
        return self._domaine

    @property
    def compteur(self) -> int:
        """Ticks écoulés (exploitant CLI)."""
        return self._ordonnanceur.tick

    def etat_cycle(self) -> dict[str, object]:
        """Cycle courant : mono-thread, échantillonné entre ticks (§25)."""
        return {
            "phase": "tour" if self._dans_tick else "attente",
            "outil_en_cours": None,
            "tick": self._ordonnanceur.tick,
        }

    def tick(self) -> RapportBoucle:
        """Un cycle complet : tiède → tâches → sélection → tour → rapport."""
        self._dans_tick = True
        try:
            changee = self._tiede()
            self._drainer_taches()
            selection = selectionner(self._situer())
            self._actifs = set(selection)
            self._plan = {niveau: outils[0] for niveau, outils in selection.items()}
            rapport = self._ordonnanceur.tour()
            alertes: list[str] = []
            if self._surveillant is not None:
                maximum = (
                    self._alertes_max
                    if self._alertes_max is not None
                    else Surveillance().alertes_rapport_max
                )
                alertes.extend(self._surveillant.alertes[-maximum:] if maximum > 0 else [])
            return RapportBoucle(
                tick=rapport.tick,
                recus=rapport.recus,
                budgets_depasse=rapport.budgets_depasse,
                selection=tuple(selection),
                directive_changee=changee,
                alertes=tuple(alertes),
            )
        finally:
            self._dans_tick = False

    def boucler(self, arret: threading.Event, delai: float = 0.05) -> None:
        """Boucle jusqu'au signal (`arret.wait` : réveil immédiat, pas de spin)."""
        while not arret.is_set():
            self.tick()
            if not arret.is_set():
                arret.wait(delai)

    def deposer(self, niveau: Priorite, effet: Effet):
        """Dépose un événement externe (API, T8.1) ; `Future` résolu au tick."""
        return self._ordonnanceur.deposer(niveau, effet)

    def _tiede(self) -> bool:
        gardien = self._surveillant
        if gardien is None:
            return False
        directive, changee = gardien.rafraichir()
        b = directive.budgets
        self._ordonnanceur.configurer_budgets(
            Budgets(
                max_tool_calls=b.max_tool_calls,
                max_ingest_per_cycle=b.max_ingest_per_cycle,
                max_cycle_ms=b.max_cycle_ms,
                max_wal_bytes=b.max_wal_bytes,
                reserve_fond=b.reserve_fond,
            )
        )
        self._politique = directive.permissions.en_politique()
        self._alertes_max = directive.monitoring.alertes_rapport_max
        if changee:
            self._hash_directive = gardien.empreinte_courante()
            flux = f"domains/{self._domaine}"
            self._magasin.append(
                flux,
                Record(
                    stream=flux,
                    op="receipt",
                    key=f"directive:{self._ordonnanceur.tick}",
                    data={
                        "sorte": "directive",
                        "hash": self._hash_directive,
                        "tick": self._ordonnanceur.tick,
                    },
                ),
            )
        return changee

    def _drainer_taches(self) -> None:
        if self._horloge is not None:
            self._registres.relever_expiration(self._horloge())
        etat = self._registres.taches()
        for niveau in (Priorite.P4, Priorite.P5, Priorite.P6):
            noms = set(outils_niveau(niveau))
            for cle in sorted(etat):
                if not cle.startswith("task:"):
                    continue
                fiche = etat[cle]
                if fiche.get("etat") != EtatTache.ATTENTE.value:
                    continue
                if fiche.get("type") in noms and fiche.get("type") in self._outils:
                    self._ordonnanceur.deposer(
                        niveau, self._consommateur(str(fiche["id"]), str(fiche["type"]))
                    )
                    break

    def _situer(self) -> Situation:
        etat = self._registres.taches()

        def en_attente(niveau: Priorite) -> tuple[str, ...]:
            noms = set(outils_niveau(niveau))
            return tuple(
                sorted(
                    str(fiche["id"])
                    for cle, fiche in etat.items()
                    if cle.startswith("task:")
                    and fiche.get("etat") == EtatTache.ATTENTE.value
                    and fiche.get("type") in noms
                )
            )

        return Situation(
            alertes_actives=tuple(self._alerteur()) if self._alerteur is not None else (),
            donnees=en_attente(Priorite.P4),
            stales=en_attente(Priorite.P5),
            fond=bool(en_attente(Priorite.P6)),
        )

    def _consommateur(self, ident: str, type_tache: str) -> Effet:
        def effet() -> ToolResult:
            try:
                self._registres.passer_etat(ident, EtatTache.COURS)
            except ValueError as exc:
                return ToolResult(status=Status.FAILED, payload={"tache": ident, "motif": str(exc)})
            try:
                recu = self._outils[type_tache]()
            except Exception as exc:  # noqa: BLE001 — outil fautif ⇒ tâche abandonnée, boucle sauve
                _LOG.exception("panne outil tâche %s", ident)
                self._registres.passer_etat(
                    ident, EtatTache.ABANDONNEE, motif=f"panne outil : {exc}"
                )
                return ToolResult(
                    status=Status.FAILED, payload={"tache": ident, "motif": f"panne outil : {exc}"}
                )
            try:
                self._registres.noter_conso(ident, recu.cost.ms, recu.cost.calls)
                self._registres.passer_etat(ident, EtatTache.TERMINEE)
            except ValueError as exc:
                return ToolResult(status=Status.FAILED, payload={"tache": ident, "motif": str(exc)})
            return recu

        return effet

    def _periodique(self, niveau: Priorite) -> ToolResult:
        nom = self._plan.get(niveau)
        if nom is None or nom not in self._outils:
            return ToolResult(
                status=Status.DEGRADE,
                payload={"niveau": niveau.value, "motif": "aucun outil planifié"},
            )
        return self._outils[nom]()


__all__ = ["borner", "Boucle", "RapportBoucle", "outils_niveau"]
