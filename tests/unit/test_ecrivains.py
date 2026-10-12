# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Garde I3 : l'ensemble des écrivains Store/Magasin est figé et revu.

L'état du graphe ne mute que via `add_edge`/`confirm`/`tombstone` (seul
`tools/ingest` écrit des arêtes — `appliquer_domaine` ignore `receipt`) ;
les autres écritures (`registry/*`, reçus) passent par `Magasin` depuis
des appelants listés ici. Tout nouveau fichier écrivain fait échouer
la garde (revue I3 explicite exigée).

Maille : appels `.append(` sur `store`/`magasin`/`_magasin` (nom ou
attribut) + `self.flux(..).append(..)` (choke WAL de `Magasin.append`).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "evidra"

# Fichiers autorisés à appeler `.append(` sur un Store/Magasin.
ECRIVAINS_AUTORISES = frozenset(
    {
        "tools/ingest.py",  # arêtes graphe (add_edge/confirm, via can())
        "memory/store.py",  # point de choke (Magasin.append → WAL)
        "memory/registres.py",  # streams registry/* (sources/alias/modèles/tâches)
        "boucle.py",  # reçu gouvernance (op receipt, sans effet d'état)
        "cli.py",  # reçu d'arrêt (op receipt, sans effet d'état)
        "arbitrage_cli.py",  # verdicts T6.4 (update_status/tombstone motivés)
    }
)


def _ecrivains(chemin: Path) -> bool:
    """Vrai si le fichier appelle `.append(` sur store/magasin/Magasin."""
    try:
        tree = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "append":
            continue
        cible = node.func.value
        if isinstance(cible, ast.Name) and cible.id in {"store", "magasin"}:
            return True
        if isinstance(cible, ast.Attribute) and cible.attr in {"store", "magasin", "_magasin"}:
            return True
        if (
            isinstance(cible, ast.Call)
            and isinstance(cible.func, ast.Attribute)
            and cible.func.attr == "flux"
        ):
            return True  # `self.flux(..).append(..)` : choke WAL de Magasin
    return False


def test_ecrivains_store_figes() -> None:
    trouves = {str(p.relative_to(SRC)) for p in sorted(SRC.rglob("*.py")) if _ecrivains(p)}
    assert trouves == ECRIVAINS_AUTORISES, f"écrivains : {sorted(trouves)}"
