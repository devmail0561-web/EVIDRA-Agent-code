# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.1 — faute : `kill -9` en cours d'écriture ⇒ 0 perte des lignes fsyncées."""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

from evidra.memory.wal import WAL


def test_kill_moins_9_sans_perte_fsync(tmp_path: Path) -> None:
    ecrivain = Path(__file__).resolve().parent / "ecrivain_wal.py"
    enfant = subprocess.Popen(
        [sys.executable, str(ecrivain), "--dossier", str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert enfant.stdout is not None
    syncs = 0
    while syncs < 2:
        ligne = enfant.stdout.readline()
        assert ligne != "", "l'écrivain est mort avant 2 syncs"
        if ligne.startswith("SYNC"):
            syncs += 1
    enfant.send_signal(signal.SIGKILL)
    enfant.wait(timeout=30)
    with WAL(tmp_path / "wal.jsonl") as relecture:
        rapport = relecture.relire()
    seqs = [e.seq for e in rapport.valides]
    assert seqs[:20] == list(range(1, 21))  # 2 syncs × 10 = 20 lignes intactes
    assert seqs == sorted(seqs)  # ordre croissant, sans doublon de seq
    assert rapport.crc_invalides == 0
