#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Exporte le JSON Schema de directive (T4.1) vers `docs/contrats/`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from evidra.directive.schema import schema_json  # noqa: E402


def main() -> None:
    cible = RACINE / "docs" / "contrats" / "directive.schema.json"
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(schema_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"écrit : {cible}")


if __name__ == "__main__":
    main()
