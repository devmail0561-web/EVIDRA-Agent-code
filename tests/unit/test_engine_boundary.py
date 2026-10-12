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


# Scaffold dev opt-in (`--essai`, jamais en prod, « À REMPLACER quand B2 ») :
# seul fichier du bridge autorisé hors liste blanche, à jeu figé.
ESSAI_AUTORISES = frozenset(
    {
        "gcn_python.constants.NODE_TYPES",
        "gcn_python.constants.RELATION_TYPES",
        "gcn_python.constants.rgcn_n_relations",
        "gcn_python.engine.GCNEngine",
        "gcn_python.frontend.bridge.GCNLatticeParser",
        "gcn_python.layer1.embedding.WordEmbedding",
        "gcn_python.layer1.features.FeatureVocabulary",
        "gcn_python.layer1.representation.UDRepresentation",
        "gcn_python.layer2.reference.MLPEncoder",
        "gcn_python.layer3.reference.RGCNLayer",
        "gcn_python.pipeline.cgnp.CGNPipeline",
    }
)


def test_liste_blanche_dans_engine_bridge():
    """Dans le bridge, seuls liste blanche (+ `essai.py` figé) touchent `gcn`."""
    bad: list[str] = []
    for path in sorted(BRIDGE.rglob("*.py")):
        trouves = violations(path.read_text())
        if path.name == "essai.py":
            if set(trouves) != ESSAI_AUTORISES:
                bad.append(f"{path.name}: dérive du scaffold ({sorted(trouves)})")
        else:
            bad.extend(f"{path.relative_to(SRC)}: {v}" for v in trouves)
    assert bad == []


def test_subprocess_gcn_reserve_engine_bridge():
    """Seul `engine_bridge` spawne `gcn` (ADR-0012/0013) ; le noyau jamais."""
    import ast as _ast

    fautifs = []
    for path in sorted(SRC.rglob("*.py")):
        if BRIDGE in path.parents or path == BRIDGE:
            continue
        arbre = _ast.parse(path.read_text())
        for noeud in _ast.walk(arbre):
            if isinstance(noeud, (_ast.Import, _ast.ImportFrom)):
                noms = [a.name for a in noeud.names] + (
                    [noeud.module] if isinstance(noeud, _ast.ImportFrom) and noeud.module else []
                )
                if any(
                    n == "subprocess" or (isinstance(n, str) and n.startswith("subprocess."))
                    for n in noms
                ):
                    fautifs.append(str(path.relative_to(SRC)))
    assert fautifs == []


def test_canari_symbole_interdit_detecte():
    # `analyze` est dans la liste blanche : autorisé à la lettre, quel que soit
    # le module (l'ambiguïté layer0/engine est tranchée par docs/engine-compat.md,
    # pas par cette garde — futur ADR).
    assert violations("from gcn_python.layer0.engine_b import analyze\n") == []
    assert violations("import gcn_python\n") != []
    assert violations("from gcn_python.reasoning.engine import reason\n") == []
    assert violations("from gcn_python.engine import GCNEngine\n") != []  # hors liste
