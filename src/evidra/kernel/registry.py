# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Registre et cycle de vie des plugins (T1.3, noyau stdlib — ADR-0005).

Découverte via `importlib.metadata` (groupes `evidra_tools` /
`evidra_adapters`), états
`discovered → validated → enabled → running → disabled | quarantined`.
Trois échecs de contrat consécutifs ⇒ `quarantined` automatique ;
`harness_required` supérieur à la version supportée ⇒ `disabled` motivé.

Le code des plugins est chargé « eager » (import seul, kilo-octets) : les
poids de modèles ne sont jamais chargés ici (cf. §12bis de l'étude).

Le registre ne nomme aucun plugin concret (I2) : il manipule des noms
fournis par les entry-points, jamais écrits en dur.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from evidra.kernel.contracts import HARNESS_VERSION
from evidra.kernel.manifest import ManifestError, manifest_from_plugin, parse_version

GROUPES = ("evidra_tools", "evidra_adapters")

SEUIL_QUARANTAINE = 3


class RegistryError(ValueError):
    """Transition illégale ou usage fautif du registre (rattaché à T1.6)."""


PluginState = StrEnum(
    "PluginState",
    {
        "DISCOVERED": "discovered",
        "VALIDATED": "validated",
        "ENABLED": "enabled",
        "RUNNING": "running",
        "DISABLED": "disabled",
        "QUARANTINED": "quarantined",
    },
)
# États du cycle de vie d'un plugin (ADR-0005).


_TRANSITIONS: Mapping[PluginState, frozenset[PluginState]] = {
    PluginState.DISCOVERED: frozenset({PluginState.VALIDATED, PluginState.DISABLED}),
    PluginState.VALIDATED: frozenset({PluginState.ENABLED, PluginState.DISABLED}),
    PluginState.ENABLED: frozenset({PluginState.RUNNING, PluginState.DISABLED}),
    PluginState.RUNNING: frozenset({PluginState.DISABLED, PluginState.QUARANTINED}),
    PluginState.DISABLED: frozenset({PluginState.ENABLED}),
    PluginState.QUARANTINED: frozenset({PluginState.DISABLED}),
}


@dataclass(slots=True)
class PluginRecord:
    """Fiche mutable d'un plugin découvert (état + motif + compteur)."""

    key: str  # nom de l'entry-point
    groupe: str
    state: PluginState = PluginState.DISCOVERED
    motif: str = ""
    echecs: int = 0
    plugin_cls: Any = None


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """Rapport de découverte : liste (nom, état, motif) — T1.3."""

    entrees: tuple[tuple[str, str, str], ...]


def _passer(record: PluginRecord, cible: PluginState, motif: str = "") -> None:
    autorisees = _TRANSITIONS[record.state]
    if cible not in autorisees:
        raise RegistryError(f"transition illégale : {record.state.value} → {cible.value}")
    record.state = cible
    record.motif = motif


class Registry:
    """Registre des plugins : découverte, validation, cycle de vie."""

    def __init__(self, supportee: tuple[int, ...] | None = None) -> None:
        support = parse_version(HARNESS_VERSION)
        assert support is not None
        self._supportee = supportee if supportee is not None else support
        self._fiches: dict[str, PluginRecord] = {}

    def discover(self, points: Mapping[str, Iterable[Any]] | None = None) -> DiscoveryReport:
        """Découvre les plugins (entry-points réels, ou `points` injectés en test)."""
        trouves = (
            dict(points)
            if points is not None
            else {g: importlib.metadata.entry_points(group=g) for g in GROUPES}
        )
        for groupe, entrees in trouves.items():
            for entree in entrees:
                cle = f"{groupe}:{entree.name}"
                self._fiches.setdefault(cle, PluginRecord(key=entree.name, groupe=groupe))
        return self.rapport()

    def approve(self, cle: str, plugin_cls: Any) -> PluginRecord:
        """Charge (eager) et valide : `validated`, ou `disabled` motivé."""
        fiche = self._fiche(cle)
        if fiche.state is not PluginState.DISCOVERED:
            raise RegistryError(f"approve exige discovered (fiche {cle})")
        try:
            manifeste = manifest_from_plugin(plugin_cls)
        except ManifestError as exc:
            _passer(fiche, PluginState.DISABLED, f"manifeste refusé : {exc}")
            return fiche
        exigee = parse_version(manifeste.harness_required)
        if exigee is None or exigee > self._supportee:
            motif = f"harness {manifeste.harness_required} > supporté ({HARNESS_VERSION})"
            _passer(fiche, PluginState.DISABLED, motif)
            return fiche
        fiche.plugin_cls = plugin_cls
        _passer(fiche, PluginState.VALIDATED)
        return fiche

    def enable(self, cle: str) -> PluginRecord:
        """Active un plugin validé (ou ré-active après `disabled` tiède)."""
        fiche = self._fiche(cle)
        _passer(fiche, PluginState.ENABLED)
        return fiche

    def disable(self, cle: str, motif: str) -> PluginRecord:
        """Désactive (code inerte, sans redémarrage — ADR-0008)."""
        fiche = self._fiche(cle)
        _passer(fiche, PluginState.DISABLED, motif)
        return fiche

    def start(self, cle: str) -> PluginRecord:
        """Passe en `running` (exécution par le scheduler)."""
        fiche = self._fiche(cle)
        _passer(fiche, PluginState.RUNNING)
        return fiche

    def note_failure(self, cle: str) -> PluginRecord:
        """Échec de contrat : 3 consécutifs ⇒ `quarantined` automatique."""
        fiche = self._fiche(cle)
        fiche.echecs += 1
        if fiche.echecs >= SEUIL_QUARANTAINE and fiche.state is PluginState.RUNNING:
            _passer(fiche, PluginState.QUARANTINED, f"{fiche.echecs} échecs consécutifs")
        return fiche

    def note_success(self, cle: str) -> PluginRecord:
        """Succès : remet le compteur d'échecs à zéro."""
        fiche = self._fiche(cle)
        fiche.echecs = 0
        return fiche

    def rapport(self) -> DiscoveryReport:
        """Liste (nom, état, motif) de toutes les fiches."""
        entrees = tuple((f.key, f.state.value, f.motif) for f in self._fiches.values())
        return DiscoveryReport(entrees=entrees)

    def _fiche(self, cle: str) -> PluginRecord:
        try:
            return self._fiches[cle]
        except KeyError:
            raise RegistryError(f"plugin inconnu : {cle}") from None
