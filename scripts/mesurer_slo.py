#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Banc SLO P1 (T2.8) : insertion, chargement, requêtes, rejeu WAL.

Sortie : objet JSON daté sur stdout, écrit dans `--sortie` si fourni.
Les chiffres remplacent les cibles : un SLO affiché est un SLO mesuré (DoD).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.bench.test_slo_p1 import (  # noqa: E402 — chemin injecté ci-dessus
    mesurer_chargement,
    mesurer_insertion,
    mesurer_requetes_p99,
    mesurer_wal_rejeu,
)


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--sortie", default="")
    opts = args.parse_args()
    rapport = {
        "date": datetime.now(UTC).isoformat(),
        "insertion_index_10k": mesurer_insertion(),
        "requetes_200_100k": mesurer_chargement(),
        "p99_causes_ms_100k": mesurer_requetes_p99(),
        "rejeu_wal_100k": mesurer_wal_rejeu(),
    }
    texte = json.dumps(rapport, indent=2)
    print(texte)
    if opts.sortie:
        Path(opts.sortie).write_text(texte + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
