# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T0.5 — garde I2 : noyau < 500 SLOC et aucun nom concret d'outil/adaptateur.

Le noyau (`kernel/`) ne dépend que des Protocols : il ne nomme aucun plugin.
La détection porte sur les identifiants et littéraux du code (commentaires et
docstrings exclus), pour éviter les faux positifs de la prose.
"""

from __future__ import annotations

import ast
import contextlib
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from sloc import sloc  # noqa: E402

KERNEL = Path(__file__).resolve().parent.parent.parent / "src" / "evidra" / "kernel"
BUDGET = 500

# Noms concrets de plugins : adaptateurs puis outils (cf. §1.3 et §9.3).
NOMS_CONCRETS = frozenset(
    {
        "local_files",
        "http_feed",
        "agent_push",
        "extract",
        "ingest",
        "query_causes",
        "query_effects",
        "query_chain",
        "query_cycles",
        "query_gaps",
        "validate",
        "counterfactual",
        "alert",
        "report",
        "fetch",
    }
)


def noms_code(path: Path) -> set[str]:
    """Identifiants + littéraux string exacts du code (hors commentaires).

    Exclut le corps de l'enum `Verb` : les six verbes (§13.3) sont le
    vocabulaire des permissions, pas des noms de plugins.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    ignore: set[int] = set()

    def _couvre(node: ast.AST) -> None:
        first = node.lineno
        last = node.end_lineno or first
        ignore.update(range(first, last + 1))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                _couvre(body[0])
        if isinstance(node, ast.ClassDef) and node.name == "Verb":
            _couvre(node)
    found: set[str] = set()
    with tokenize.open(path) as stream:
        for tok in tokenize.generate_tokens(stream.readline):
            if tok.type == tokenize.NAME and tok.start[0] not in ignore:
                found.add(tok.string)
            elif tok.type == tokenize.STRING and tok.start[0] not in ignore:
                with contextlib.suppress(SyntaxError, ValueError):
                    found.add(ast.literal_eval(tok.string))
    return found


def test_noyau_sous_budget_sloc():
    total = sum(sloc(p) for p in sorted(KERNEL.rglob("*.py")))
    assert total < BUDGET, f"noyau à {total} SLOC (budget {BUDGET})"


def test_noyau_sans_nom_concret_de_plugin():
    bad: list[str] = []
    for path in sorted(KERNEL.rglob("*.py")):
        clash = noms_code(path) & NOMS_CONCRETS
        bad.extend(f"{path.name}: {n}" for n in sorted(clash))
    assert bad == []
