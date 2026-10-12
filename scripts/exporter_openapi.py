#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Exporte l'OpenAPI de l'API (T8.2) vers `docs/contrats/` (extra `api`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from evidra.api.app import creer_app  # noqa: E402


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Exporte l'OpenAPI Evidra")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--directive", required=True)
    args = parser.parse_args()

    from evidra.api.pont import contexte_depuis_rapport
    from evidra.boot.demarrage import demarrer

    rapport = demarrer(data_dir=Path(args.data_dir), directive_path=Path(args.directive))
    assert rapport.boucle is not None
    ctx = contexte_depuis_rapport(rapport, Path(args.data_dir))
    assert ctx is not None
    schema = creer_app(rapport.boucle, ctx, directive_path=Path(args.directive)).openapi()
    assert rapport.magasin is not None
    rapport.magasin.close()
    cible = RACINE / "docs" / "contrats" / "openapi.json"
    cible.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"écrit : {cible} ({len(schema.get('paths', {}))} chemins)")


if __name__ == "__main__":
    main()
