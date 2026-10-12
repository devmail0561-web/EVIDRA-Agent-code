# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Auto-interrogation (T5.9) : lecture pure — status, tâche, cycle.

Tous les compteurs existent déjà (WAL, index, cache, registres, boucle) :
seul le verbe manquait. `epoch` : non vérifiable sans toucher au moteur (I1,
amendement en attente) — `None` explicite, jamais inventé.
"""

from __future__ import annotations

import time
from typing import Any

from evidra.memory.memoire import Memoire
from evidra.memory.registres import Registres
from evidra.memory.store import Magasin


def apercu(
    magasin: Magasin,
    memoires: dict[str, Memoire],
    *,
    demarre_a: float | None = None,
    degraded: bool | None = None,
) -> dict[str, Any]:
    """`status()` : arêtes, nœuds, domaines, seq WAL, cache, epoch, uptime, degraded."""
    seqs: dict[str, int] = {}
    for cle in magasin.inventorier():
        seqs[cle] = magasin.derniers_seq().get(cle, 0)
    return {
        "edges": sum(len(m.entites) for m in memoires.values()),
        "nodes": sum(m.index.stats()["labels"] for m in memoires.values()),
        "domains": sorted(memoires),
        "wal_seq": seqs,
        "cache": {d: m.cache.compteurs() for d, m in sorted(memoires.items())},
        "epoch": None,
        "epoch_note": "non vérifié (I1, amendement en attente)",
        "uptime_s": round(time.monotonic() - demarre_a, 2) if demarre_a is not None else None,
        "degraded": degraded,
    }


def tache(registres: Registres, ident: str) -> dict[str, Any] | None:
    """État d'une tâche : id, état, budget/consommé/restant, deadline, motif."""
    fiche = registres.tache(ident)
    if fiche is None:
        return None
    try:
        budget = float(fiche.get("budget", 0.0))
    except (TypeError, ValueError):
        budget = 0.0
    consomme = float(fiche.get("consomme_ms", 0.0) or 0.0)
    return {
        "id": fiche.get("id", ident),
        "etat": fiche.get("etat"),
        "budget": budget,
        "consomme_ms": consomme,
        "consomme_appels": int(fiche.get("consomme_appels", 0) or 0),
        "restant_ms": budget - consomme if isinstance(fiche.get("budget"), (int, float)) else None,
        "deadline": fiche.get("deadline"),
        "motif": fiche.get("motif", ""),
    }


def cycle(boucle: Any) -> dict[str, Any]:
    """Cycle courant : échantillonné entre ticks (mono-thread, §25)."""
    return boucle.etat_cycle()
