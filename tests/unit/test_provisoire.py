# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Garde I9 : toute constante numérique de code est déclarée (registre)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from lint_provisoire import constantes, ecarts  # noqa: E402

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "evidra"


def test_constantes_declarees() -> None:
    assert ecarts(SRC) == []


def test_constante_non_declaree_detectee(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("FOO = 1\n", encoding="utf-8")
    assert any("non déclarée" in e and "mod.FOO" in e for e in ecarts(tmp_path))


def test_valeur_derivee_detectee(tmp_path: Path) -> None:
    dossier = tmp_path / "memory"
    dossier.mkdir()
    (dossier / "snapshot.py").write_text("VERSION_SNAPSHOT = 2\n", encoding="utf-8")
    assert any("dérivée" in e and "VERSION_SNAPSHOT" in e for e in ecarts(tmp_path))


def test_maille_documentee(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("X: int = 5\nY = -1\nclass C:\n    Z = 3\n", encoding="utf-8")
    assert constantes(tmp_path) == {}, "maille : module `NOM = <nombre>` seul (cf. docstring)"
