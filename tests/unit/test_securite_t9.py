# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T9.6/T9.9/T9.10 — séparation donnée/instruction, egress whitelist, rétention."""

from __future__ import annotations

import ast
from pathlib import Path

from evidra.kernel.contracts import Status, ToolResult
from evidra.output.human import formater_humain
from evidra.output.llm import formater_llm
from evidra.security.egress import hote_autorise, verifier_egress

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "evidra"


def _recu() -> ToolResult:
    return ToolResult(
        status=Status.OK,
        payload={
            "reponses": [
                {
                    "source": "pluie",
                    "cible": "inondation",
                    "relation": "cause",
                    "confiance": 0.9,
                    "provenance": {
                        "ref": "doc://1",
                        "span": "synthetic",
                        "extraction_method": "m",
                        "model_version": "v",
                        "extracted_at": "t",
                    },
                },
            ]
        },
    )


def test_llm_donnees_seules_jamais_instruction() -> None:
    compact = formater_llm(_recu())
    assert set(compact) <= {
        "faits",
        "sources",
        "confiance_min",
        "sans_ref_ecartees",
        "avertissements",
        "cout_ms",
    }
    assert "instruction" not in str(compact).lower()
    assert compact["sources"] == ["doc://1"]


def test_humain_cite_quote_attribue() -> None:
    texte = formater_humain(_recu())
    assert "« pluie »" in texte and "« inondation »" in texte
    assert "Sources :" in texte and "doc://1" in texte


def test_gabarits_sans_concat_interpretee() -> None:
    """AST : aucun gabarit output/ ne concatène du texte source en instruction."""
    for nom in ("llm.py", "human.py", "agent.py", "alert.py"):
        tree = ast.parse((SRC / "output" / nom).read_text(encoding="utf-8"))
        src = ast.dump(tree)
        assert "system prompt" not in (SRC / "output" / nom).read_text().lower()
        assert "oublie tes instructions" not in (SRC / "output" / nom).read_text().lower()
        assert isinstance(src, str)


def test_egress_whitelist() -> None:
    assert hote_autorise("https://alertes.example.com/hook", ["alertes.example.com"]) is True
    assert hote_autorise("https://evil.example.org/hook", ["alertes.example.com"]) is False
    assert hote_autorise("https://ALERTES.example.com/x", ["alertes.example.com"]) is True
    assert hote_autorise("pas-une-url", ["alertes.example.com"]) is False
    assert hote_autorise("https://nimporte.où/x", None) is True
    ok, _ = verifier_egress("https://alertes.example.com/hook", ["alertes.example.com"])
    assert ok
    ok, motif = verifier_egress("https://evil.example.org/hook", ["alertes.example.com"])
    assert not ok and "hors liste" in motif
    ok, _ = verifier_egress("", ["alertes.example.com"])
    assert not ok


def test_egress_refuse_avant_envoi() -> None:
    import tempfile

    from evidra.memory.registres import Registres
    from evidra.memory.sources import SeuilsSources
    from evidra.memory.store import Magasin
    from evidra.tools.alert import OutilAlert

    with Magasin(Path(tempfile.mkdtemp()) / "d") as magasin:
        outil = OutilAlert(
            {},
            Registres(magasin),
            [],
            0.8,
            SeuilsSources(),
            Path(tempfile.mkdtemp()) / "a.jsonl",
            lambda: "t",
            endpoint="https://evil.example.org/hook",
            egress_hotes=["alertes.example.com"],
        )
        assert outil._egresser({}) is not None
        assert "hors liste" in (outil._egresser({}) or "")


def test_retention_candidates_et_purge(tmp_path: Path) -> None:
    from evidra.memory.envelope import CirCore, Provenance
    from evidra.memory.memoire import Memoire
    from evidra.memory.retention import candidates

    assert candidates({}, maintenant_iso="t", retention_jours=None) == []
    memo = Memoire("code")
    memo.observer(
        CirCore(
            source="a",
            target="b",
            relation="cause",
            confidence=0.9,
            provenance=Provenance(
                ref="doc://1",
                span="synthetic",
                extraction_method="m",
                model_version="v",
                extracted_at="2020-01-01T00:00:00+00:00",
            ),
        ),
        channel="t",
        fiabilite=0.5,
        horodatage="2020-01-01T00:00:00+00:00",
    )
    triplet = next(iter(memo.entites))
    assert candidates(
        memo.entites, maintenant_iso="2020-06-01T00:00:00+00:00", retention_jours=30
    ) == [triplet]
    assert (
        candidates(memo.entites, maintenant_iso="2020-01-05T00:00:00+00:00", retention_jours=30)
        == []
    )
