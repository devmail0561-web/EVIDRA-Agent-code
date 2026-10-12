# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.6 — CLI : status lecture seule, query avec provenance, compact, ingest, run."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from evidra.boot.demarrage import demarrer
from evidra.cli import main
from evidra.kernel.contracts import Context
from evidra.memory.envelope import CirCore, Provenance


def _directive() -> dict:
    return {
        "agent_id": "t",
        "domain": "code",
        "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
    }


def _noyau(ref: str = "doc://graine") -> CirCore:
    return CirCore(
        source="Surchauffe",
        target="panne",
        relation="cause",
        confidence=0.9,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )


def _amorcer(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(json.dumps(_directive()), encoding="utf-8")
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.ingest is not None and rapport.magasin is not None
    ctx = Context(store=rapport.magasin, domain="code")
    rapport.ingest.run(ctx, {"noyaux": [_noyau()], "channel": "test"})
    rapport.magasin.close()
    return data


def test_status_vide_lecture_seule(tmp_path: Path, capsys) -> None:
    data = tmp_path / "data"
    data.mkdir()
    assert main(["status", "--data-dir", str(data)]) == 0
    rapport = json.loads(capsys.readouterr().out)
    assert rapport["manifeste"] == {} and rapport["streams"] == []
    assert not (data / "sa.lock").exists()  # aucun verrou : vraiment lecture seule


def test_status_apres_boot(tmp_path: Path, capsys) -> None:
    data = _amorcer(tmp_path)
    assert main(["status", "--data-dir", str(data)]) == 0
    rapport = json.loads(capsys.readouterr().out)
    assert rapport["manifeste"]["harness"] == "0.1.0"
    assert any(s["stream"] == "domains/code" for s in rapport["streams"])


def test_status_manifeste_corrompu_tolerant(tmp_path: Path, capsys) -> None:
    data = _amorcer(tmp_path)
    (data / "sa_manifest.json").write_text("{ pourri", encoding="utf-8")
    (data / "ailleurs" / "wal.jsonl").parent.mkdir(parents=True)
    (data / "ailleurs" / "wal.jsonl").write_text("", encoding="utf-8")
    assert main(["status", "--data-dir", str(data)]) == 0
    rapport = json.loads(capsys.readouterr().out)
    assert rapport["manifeste"] == {}
    assert rapport["invalides"] == ["ailleurs"]
    assert any("manifeste" in a for a in rapport["avertissements"])


def test_query_inconnu(tmp_path: Path) -> None:
    assert main(["query", "causes", "x", "--data-dir", str(tmp_path), "--domaine", "code"]) == 1


def test_query_provenance(tmp_path: Path, capsys) -> None:
    data = _amorcer(tmp_path)
    assert (
        main(["query", "effects", "surchauffe", "--data-dir", str(data), "--domaine", "code"]) == 0
    )
    rapport = json.loads(capsys.readouterr().out)
    assert len(rapport["reponses"]) == 1
    assert rapport["reponses"][0]["ref"] == "doc://graine"  # I4 jusqu'au CLI
    assert main(["query", "causes", "panne", "--data-dir", str(data), "--domaine", "code"]) == 0
    assert len(json.loads(capsys.readouterr().out)["reponses"]) == 1


def test_compact(tmp_path: Path) -> None:
    data = _amorcer(tmp_path)
    assert (data / "domains" / "code" / "wal.jsonl").stat().st_size > 0
    assert main(["compact", "--data-dir", str(data), "--domaine", "code"]) == 0
    assert (data / "domains" / "code" / "wal.jsonl").stat().st_size == 0


def test_ingest_refuse_sans_moteur(tmp_path: Path, capsys) -> None:
    directive = tmp_path / "directive.json"
    directive.write_text(json.dumps(_directive()), encoding="utf-8")
    (tmp_path / "doc.md").write_text("La pluie cause des inondations.\n", encoding="utf-8")
    rc = main(
        [
            "ingest",
            str(tmp_path / "doc.md"),
            "--directive",
            str(directive),
            "--data-dir",
            str(tmp_path / "data"),
        ]
    )
    assert rc == 2
    assert "B2" in capsys.readouterr().err


def test_ingest_essai_fixture(tmp_path: Path, capsys) -> None:
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
                "quality": {"min_confidence": 0.0, "min_extraction_method": "ml_python"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "a.md").write_text(
        "Rien de causal ici, juste du texte.\n", encoding="utf-8"
    )
    (tmp_path / "corpus" / "b.md").write_text(
        "Les ventes baissent donc les prix augmentent.\n", encoding="utf-8"
    )
    (tmp_path / "corpus" / "c.md").write_text(
        "Le gel detruit les cultures, ce qui entraine des penuries.\n", encoding="utf-8"
    )
    rc = main(
        [
            "ingest",
            str(tmp_path / "corpus"),
            "--directive",
            str(directive),
            "--data-dir",
            str(tmp_path / "data"),
            "--essai",
        ]
    )
    assert rc == 0
    total = json.loads(capsys.readouterr().out)
    assert total["documents"] == 3 and total["ajoutees"] + total["confirmees"] >= 1


def test_run_sigterm_arret_propre(tmp_path: Path) -> None:
    directive = tmp_path / "directive.json"
    directive.write_text(json.dumps(_directive()), encoding="utf-8")
    data = tmp_path / "data"
    cmd = [
        sys.executable,
        "-c",
        "import sys; from evidra.cli import main; sys.exit(main())",
        "run",
        "--directive",
        str(directive),
        "--data-dir",
        str(data),
    ]
    enfant = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert enfant.stdout is not None
    pret = False
    debut = time.monotonic()
    while time.monotonic() - debut < 30.0:
        ligne = enfant.stdout.readline()
        if not ligne:
            break
        if '"pret": true' in ligne:
            pret = True
            break
    assert pret, "démarrage sans marqueur"
    enfant.send_signal(signal.SIGTERM)
    assert enfant.wait(timeout=30) == 0
    with open(data / "domains" / "code" / "wal.jsonl", "rb") as flux:
        contenu = flux.read().decode("utf-8")
    assert '"sorte":"arret"' in contenu  # T4.7 : reçu final écrit (JSON canonique)
    from evidra.memory.store import Magasin

    with Magasin(data):
        pass  # verrou libéré : réouverture possible (T4.7)
