#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Compte les SLOC d'un répertoire : lignes portant du code, hors lignes
vides, commentaires et docstrings (T0.5, garde I2 : noyau < 500 SLOC).

Déterministe : `tokenize` + plages de docstrings via `ast`.

Usage : `python scripts/sloc.py src/evidra/kernel`
"""

from __future__ import annotations

import ast
import sys
import tokenize
from pathlib import Path

_IGNORED = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)


def sloc(path: Path) -> int:
    """Nombre de lignes portant du code dans un fichier Python."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                first = body[0].lineno
                last = body[0].end_lineno or first
                docstrings.update(range(first, last + 1))
    lines: set[int] = set()
    with tokenize.open(path) as stream:
        for tok in tokenize.generate_tokens(stream.readline):
            if tok.type in _IGNORED:
                continue
            if tok.start[0] in docstrings:
                continue
            lines.add(tok.start[0])
    return len(lines)


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("src/evidra/kernel")
    total = sum(sloc(p) for p in sorted(target.rglob("*.py")))
    print(f"{total} SLOC ({target})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
