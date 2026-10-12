# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.5 — démarrage : 5 phases, degraded motivé, refus nets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidra.boot.demarrage import DemarrageError, demarrer
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.store import Magasin


def _directive() -> dict:
    return {
        "agent_id": "test",
        "domain": "code",
        "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
    }


def _prep(tmp_path: Path) -> tuple[Path, Path]:
    directive = tmp_path / "directive.json"
    directive.write_text(json.dumps(_directive()), encoding="utf-8")
    return tmp_path / "data", directive


def _noyau(ref: str) -> CirCore:
    return CirCore(
        source="Authentification",
        target="accès",
        relation="cause",
        confidence=0.87,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="gcn-core-4.0.0",
            extracted_at="t",
        ),
    )


def test_premier_demarrage_complet(tmp_path: Path) -> None:
    data, directive = _prep(tmp_path)
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.degraded is False and rapport.motifs == ()
    assert set(rapport.phases) == {"manifeste", "wal", "registres", "moteur", "domaines", "boucle"}
    assert rapport.phases["manifeste"]["premier_demarrage"] is True
    assert rapport.boucle is not None and rapport.magasin is not None
    assert rapport.registres is not None and rapport.ingest is not None
    assert rapport.directive is not None and rapport.directive.domain == "code"
    assert (data / "sa_manifest.json").exists()
    assert rapport.boucle.tick().tick == 1
    rapport.magasin.close()


def test_second_demarrage_non_degraded(tmp_path: Path) -> None:
    data, directive = _prep(tmp_path)
    premier = demarrer(data_dir=data, directive_path=directive)
    premier.magasin.close()
    second = demarrer(data_dir=data, directive_path=directive)
    assert second.degraded is False
    assert second.phases["manifeste"]["premier_demarrage"] is False
    second.magasin.close()


def test_manifeste_divergent_degraded_motive(tmp_path: Path) -> None:
    data, directive = _prep(tmp_path)
    premier = demarrer(data_dir=data, directive_path=directive)
    premier.magasin.close()
    manifeste = json.loads((data / "sa_manifest.json").read_text(encoding="utf-8"))
    manifeste["harness"] = "0.0.0"
    (data / "sa_manifest.json").write_text(json.dumps(manifeste), encoding="utf-8")
    second = demarrer(data_dir=data, directive_path=directive)
    assert second.degraded is True
    assert any("harness" in m for m in second.motifs)
    assert second.boucle is not None  # poursuite explicite, pas silencieuse
    second.magasin.close()


def test_directive_manquante_refus_net(tmp_path: Path) -> None:
    with pytest.raises(DemarrageError):
        demarrer(data_dir=tmp_path / "data", directive_path=tmp_path / "absente.json")


def test_verrou_pris_refus_net(tmp_path: Path) -> None:
    data, directive = _prep(tmp_path)
    with Magasin(data), pytest.raises(DemarrageError):
        demarrer(data_dir=data, directive_path=directive)


def test_redemarrage_meme_etat(tmp_path: Path) -> None:
    from evidra.kernel.contracts import Context

    data, directive = _prep(tmp_path)
    premier = demarrer(data_dir=data, directive_path=directive)
    assert (
        premier.ingest is not None and premier.magasin is not None and premier.registres is not None
    )
    ctx = Context(store=premier.magasin, domain="code")
    recu = premier.ingest.run(
        ctx, {"noyaux": [_noyau("doc://1"), _noyau("doc://2")], "channel": "test"}
    )
    assert recu.payload["ajoutees"] == 1 and recu.payload["confirmees"] == 1
    premier.registres.creer_tache("k1", "essai", 5.0, "2030-01-01T00:00:00+00:00")
    premier.magasin.close()
    second = demarrer(data_dir=data, directive_path=directive)
    assert len(second.memoires["code"].entites) == 1
    assert second.registres is not None
    assert second.registres.tache("k1")["etat"] == "pending"
    second.magasin.close()


def test_demarrage_a_froid_trace(tmp_path: Path) -> None:
    data, directive = _prep(tmp_path)
    rapport = demarrer(data_dir=data, directive_path=directive)
    try:
        assert rapport.phases["domaines"]["demarrage_a_froid"] is True
        assert rapport.phases["domaines"]["entites"] == 0
    finally:
        assert rapport.magasin is not None
        rapport.magasin.close()


def test_jour_zero_unconfirmed_normal(tmp_path: Path) -> None:
    from evidra.kernel.contracts import Context
    from evidra.memory.memoire import Memoire
    from evidra.tools.validate import OutilValider

    data, directive = _prep(tmp_path)
    rapport = demarrer(data_dir=data, directive_path=directive)
    try:
        assert rapport.magasin is not None
        ctx = Context(store=rapport.magasin, domain="code")
        recu = OutilValider({"code": Memoire("code")}).run(
            ctx, {"claim": {"source": "x", "relation": "cause", "cible": "y"}}
        )
        assert recu.payload["verdict"] == "UNCONFIRMED"  # jour 0 : normal, pas un échec
    finally:
        assert rapport.magasin is not None
        rapport.magasin.close()
