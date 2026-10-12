# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Protocole moteur (T3.1) : ce que la coquille exige, sans importer `gcn`.

Le moteur réel (`GCNEngine`) est injecté par le démarrage (T4.5) ; ici seul
le contrat compte (inversion de dépendance). `engine_bridge` reste le seul
paquet autorisé à toucher au moteur (I1) — y compris en abstraction.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any, Protocol, runtime_checkable


def version_moteur() -> str:
    """Version du moteur installé (`unknown` si introuvable — jamais levée)."""
    try:
        return importlib.metadata.version("gcn-python")
    except Exception:  # noqa: BLE001 — absence = info, pas erreur
        try:
            import gcn_python

            return getattr(gcn_python, "__version__", "unknown")
        except Exception:  # noqa: BLE001
            return "unknown"


@runtime_checkable
class Moteur(Protocol):
    """Surface utilisée : `analyze_batch` (+ `analyze`, T3.5 l'étendra)."""

    def analyze_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """Phrases pré-segmentées → CIRs (dédup M1b côté moteur)."""
        ...
