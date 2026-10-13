# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Garde ADR-0014 : frontière `memory/` par rôle (AST, sans exécution).

- `memory.envelope` : autorisé partout (types purs) ;
- `memory.memoire` : outils uniquement, lecture sur injectées ;
- `memory.store` / `Magasin` : ni outils ni adaptateurs (écritures via
  `ctx.store`, I3) ; adaptateurs : ni `memoire` ni écriture.
Tout nouvel import hors règle fait échouer la garde (revue explicite exigée).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "evidra"

# Modules `memory.*` dont l'import est scruté (envelope = autorisé partout).
ETAT = {"evidra.memory.memoire", "evidra.memory.store", "evidra.memory.registres"}


def _imports(chemin: Path) -> set[str]:
    tree = ast.parse(chemin.read_text(encoding="utf-8"))
    trouves = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            trouves.add(node.module)
        elif isinstance(node, ast.Import):
            trouves.update(a.name for a in node.names)
    return trouves


def _magasin(chemin: Path) -> bool:
    tree = ast.parse(chemin.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.Name) and node.id == "Magasin" for node in ast.walk(tree))


def test_adaptateurs_envelope_seule() -> None:
    for nom in ("local_files.py", "agent_push.py", "http_feed.py"):
        imports = _imports(SRC / "adapters" / nom)
        assert not (imports & ETAT), f"{nom} : {sorted(imports & ETAT)}"
        assert not _magasin(SRC / "adapters" / nom), f"{nom} : Magasin"


def test_outils_jamais_store_direct() -> None:
    for chemin in sorted((SRC / "tools").glob("*.py")):
        imports = _imports(chemin)
        assert "evidra.memory.store" not in imports, chemin.name
        assert not _magasin(chemin), chemin.name
