# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.5 — faute : crash sans close ⇒ redémarrage à l'identique (état + tâches)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evidra.boot.demarrage import demarrer


def test_crash_puis_redemarrage_identique(tmp_path: Path) -> None:
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
            }
        ),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    aide = Path(__file__).resolve().parent / "aide_demarrage.py"
    enfant = subprocess.run(
        [sys.executable, str(aide), "--data-dir", str(data), "--directive", str(directive)],
        timeout=120,
    )
    assert enfant.returncode != 0  # mort anormale, sans close
    rapport = demarrer(data_dir=data, directive_path=directive)
    try:
        assert len(rapport.memoires["code"].entites) == 1
        assert rapport.registres is not None
        assert rapport.registres.tache("k1")["etat"] == "pending"
    finally:
        assert rapport.magasin is not None
        rapport.magasin.close()
