# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T0.4 — garde I1 : frontière moteur (test AST, complément de .importlinter).

Règle : seul `evidra.engine_bridge` peut importer du code `gcn*`, et
uniquement les symboles de la liste blanche
(`analyze`, `analyze_batch`, `reason`, `reason_question`, `verify_path`,
`CausalGraph`). Tout autre import fait échouer la CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "evidra"
BRIDGE = SRC / "engine_bridge"

WHITELIST = {
    "analyze",
    "analyze_batch",
    "reason",
    "reason_question",
    "verify_path",
    "CausalGraph",
}


def violations(source: str) -> list[str]:
    """Symboles `gcn*` importés hors liste blanche dans `source`."""
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"gcn_python", "gcn"} or alias.name.startswith(
                    ("gcn_python.", "gcn.")
                ):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "gcn_python" or module.startswith("gcn_python."):
                for alias in node.names:
                    if alias.name != "*" and alias.name not in WHITELIST:
                        found.append(f"{module}.{alias.name}")
                if any(alias.name == "*" for alias in node.names):
                    found.append(f"{module}.*")
    return found


def test_aucun_import_moteur_hors_engine_bridge():
    bad: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if BRIDGE in path.parents or path == BRIDGE:
            continue
        bad.extend(f"{path.relative_to(SRC)}: {v}" for v in violations(path.read_text()))
    assert bad == []


def test_canari_symbole_interdit_detecte():
    # `analyze` est dans la liste blanche : autorisé à la lettre, quel que soit
    # le module (l'ambiguïté layer0/engine est tranchée par docs/engine-compat.md,
    # pas par cette garde — futur ADR).
    assert violations("from gcn_python.layer0.engine_b import analyze\n") == []
    assert violations("import gcn_python\n") != []
    assert violations("from gcn_python.reasoning.engine import reason\n") == []
    assert violations("from gcn_python.engine import GCNEngine\n") != []  # hors liste
