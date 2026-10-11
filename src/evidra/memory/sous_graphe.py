# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Sous-graphe borné (T3.4) : BFS exact sur l'index, plafonds moteur.

À partir de nœuds amorces, BFS limité en profondeur sur l'adjacence exacte
(`sortants`/`entrants`, jamais le repli lexical) ; au-delà des plafonds
(500 nœuds / 2000 arêtes = `MAX_NODES`/`MAX_EDGES` constatés du moteur, T3.5),
on compte `tronque` au lieu d'inclure — ce qui passe au moteur ne dépasse
jamais le plafond (acceptation T3.4). Le `tronque` remonte dans le reçu (T5.2).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from evidra.memory.envelope import normaliser_label
from evidra.memory.index import Index

# Plafonds alignés sur le moteur (constatés : MAX_NODES/MAX_EDGES, T3.5).
PROFONDEUR_DEFAUT = 2
MAX_NOEUDS = 500
MAX_ARETES = 2000


@dataclass(frozen=True, slots=True)
class Decoupe:
    """Ids retenus + compteur explicite de ce que le plafond a coupé."""

    ids: tuple[str, ...]
    tronque: int


def decouper(
    index: Index,
    amorces: list[str],
    *,
    profondeur: int = PROFONDEUR_DEFAUT,
    max_noeuds: int = MAX_NOEUDS,
    max_aretes: int = MAX_ARETES,
) -> Decoupe:
    """BFS depuis `amorces` (labels bruts) : ids bornés + `tronque`."""
    vus_noeuds: set[str] = set()
    vus_aretes: set[str] = set()
    tronque = 0
    frontiere: deque[tuple[str, int]] = deque()
    for amorce in amorces:
        noeud = normaliser_label(amorce)
        if noeud and noeud not in vus_noeuds:
            if len(vus_noeuds) >= max_noeuds:
                tronque += 1
            else:
                vus_noeuds.add(noeud)
                frontiere.append((noeud, 0))
    while frontiere:
        noeud, niveau = frontiere.popleft()
        if niveau >= profondeur:
            continue
        for ident in index.sortants(noeud) + index.entrants(noeud):
            bouts = index.bouts(ident)
            if bouts is None or ident in vus_aretes:
                continue
            nouveaux = {v for v in (bouts[0], bouts[1]) if v not in vus_noeuds}
            if len(vus_aretes) >= max_aretes or len(vus_noeuds) + len(nouveaux) > max_noeuds:
                tronque += 1
                continue
            vus_aretes.add(ident)
            for voisin in (bouts[0], bouts[1]):
                if voisin not in vus_noeuds:
                    vus_noeuds.add(voisin)
                    frontiere.append((voisin, niveau + 1))
    return Decoupe(ids=tuple(sorted(vus_aretes)), tronque=tronque)
