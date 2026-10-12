# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Protocole moteur (T3.1) : ce que la coquille exige, sans importer `gcn`.

Le moteur réel (`GCNEngine`) est injecté par le démarrage (T4.5) ; ici seul
le contrat compte (inversion de dépendance). `engine_bridge` reste le seul
paquet autorisé à toucher au moteur (I1) — y compris en abstraction.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from evidra.util import version_moteur as version_moteur

__all__ = ["Moteur", "version_moteur"]


@runtime_checkable
class Moteur(Protocol):
    """Surface utilisée : `analyze_batch` (+ `analyze`, T3.5 l'étendra)."""

    def analyze_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """Phrases pré-segmentées → CIRs (dédup M1b côté moteur)."""
        ...
