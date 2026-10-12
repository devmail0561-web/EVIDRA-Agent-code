# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Rechargement tiède (T4.2, ADR-0008) : directive relue, plugins on/off sans restart.

`Surveillant.rafraichir()` : mtime+hash inchangés ⇒ `(courante, False)` ;
sinon recharge — succès : diff des sources + bascule (`courante`, True),
application au registre (retirés ⇒ `disable`, ajoutés connus ⇒ `enable`,
échec ⇒ alerte, jamais levée) ; échec (illisible/invalide) : ancienne
conservée + alerte. `empreinte_courante()` (sha) part au WAL en reçu (T4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from evidra.directive.loader import charger, empreinte_fichier
from evidra.directive.schema import Directive
from evidra.kernel.registry import Registry, RegistryError
from evidra.logging import DirectiveError


@dataclass(frozen=True, slots=True)
class DiffSources:
    """Diff des sources entre deux directives (par nom d'adaptateur)."""

    ajoutees: tuple[str, ...]
    retirees: tuple[str, ...]


def diff_sources(ancienne: Directive, nouvelle: Directive) -> DiffSources:
    """Compare les `adapter` déclarés (unicité supposée, documentée)."""
    avant = {s.adapter for s in ancienne.sources}
    apres = {s.adapter for s in nouvelle.sources}
    return DiffSources(ajoutees=tuple(sorted(apres - avant)), retirees=tuple(sorted(avant - apres)))


class Surveillant:
    """Garde une directive vivante : recharge tiède + alertes bornées."""

    def __init__(
        self, chemin: Path, directive: Directive, registre: Registry | None = None
    ) -> None:
        self._chemin = chemin
        self._courante = directive
        self._registre = registre
        try:
            self._vue = empreinte_fichier(chemin)
        except OSError:
            self._vue = (0, "")
        self.alertes: list[str] = []

    @property
    def courante(self) -> Directive:
        """Directive en vigueur (jamais invalide)."""
        return self._courante

    def empreinte_courante(self) -> str:
        """sha256 du fichier en vigueur (reçu WAL, T4.4)."""
        return self._vue[1]

    def rafraichir(self) -> tuple[Directive, bool]:
        """Relit si le fichier a bougé ; `(courante, changée)`."""
        try:
            vue = empreinte_fichier(self._chemin)
        except OSError:
            self._alerter(f"directive illisible, ancienne conservée : {self._chemin}")
            return self._courante, False
        if vue == self._vue:
            return self._courante, False
        try:
            nouvelle = charger(self._chemin)
        except DirectiveError as exc:
            self._alerter(f"directive rejetée, ancienne conservée : {exc}")
            return self._courante, False
        diff = diff_sources(self._courante, nouvelle)
        self._courante = nouvelle
        self._vue = vue
        self._appliquer(diff)
        return self._courante, True

    def _appliquer(self, diff: DiffSources) -> None:
        if self._registre is None:
            return
        for nom in diff.retirees:
            try:
                self._registre.disable(f"evidra_adapters:{nom}", "retiré de la directive")
            except RegistryError as exc:
                self._alerter(f"retrait {nom} impossible : {exc}")
        for nom in diff.ajoutees:
            try:
                self._registre.enable(f"evidra_adapters:{nom}")
            except RegistryError as exc:
                self._alerter(f"ajout {nom} impossible : {exc} (découverte au démarrage, T4.5)")

    def _alerter(self, motif: str) -> None:
        self.alertes.append(motif)
        del self.alertes[:-100]
