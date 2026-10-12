# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T7.2 — alertes : persistance, dédup, outil, egress dégradé, P1."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from evidra.boot.demarrage import demarrer
from evidra.kernel.contracts import Context, Status, Tool
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.registres import Registres
from evidra.memory.sources import SeuilsSources
from evidra.memory.store import Magasin
from evidra.monitor.alerts import doit_emettre
from evidra.tools.alert import OutilAlert


def _magasin(tmp: Path) -> Magasin:
    return Magasin(tmp / "data")


def test_doit_emettre_fenetre() -> None:
    t0 = "2026-01-01T00:00:00+00:00"
    assert doit_emettre(None, maintenant_iso=t0, fenetre_s=3600) is True
    assert doit_emettre(t0, maintenant_iso="2026-01-01T00:30:00+00:00", fenetre_s=3600) is False
    assert doit_emettre(t0, maintenant_iso="2026-01-01T02:00:00+00:00", fenetre_s=3600) is True
    assert doit_emettre(None, maintenant_iso=t0, fenetre_s=3600, acquittee=True) is False
    assert doit_emettre("illisible", maintenant_iso=t0, fenetre_s=3600) is True


def test_registre_alertes_cycle(tmp_path: Path) -> None:
    with _magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        assert registres.alertes_actives() == {}
        registres.lever_alerte("k1", {"nom": "n", "severite": "critique"})
        assert set(registres.alertes_actives()) == {"k1"}
        assert registres.dernier_envoi("k1") is None
        registres.noter_envoi("k1", "2026-01-01T00:00:00+00:00")
        assert registres.dernier_envoi("k1") == "2026-01-01T00:00:00+00:00"
        registres.acquitter_alerte("k1", motif="vu")
        assert registres.alertes_actives() == {}
        try:
            registres.acquitter_alerte("k1", motif="")
            raise AssertionError("motif vide accepté")
        except ValueError:
            pass
        try:
            registres.acquitter_alerte("fantome", motif="x")
            raise AssertionError("inconnue acceptée")
        except ValueError:
            pass


def _noyau(src: str, ref: str = "doc://1") -> CirCore:
    return CirCore(
        source=src,
        target="panne",
        relation="cause",
        confidence=0.9,
        provenance=Provenance(
            ref=ref, span="synthetic", extraction_method="m", model_version="v", extracted_at="t"
        ),
    )


def _outil(tmp_path: Path, magasin: Magasin, motifs: list | None = None) -> OutilAlert:
    memo = Memoire("code")
    memo.observer(_noyau("ransomware x"), channel="t", fiabilite=0.5, horodatage="t")
    return OutilAlert(
        {"code": memo},
        Registres(magasin),
        ["ransomware"] if motifs is None else motifs,
        0.80,
        SeuilsSources(),
        tmp_path / "alerts.jsonl",
        lambda: "2026-01-01T00:00:00+00:00",
    )


def test_conforme_et_manifeste() -> None:
    assert isinstance(_outil(Path(tempfile.mkdtemp()), Magasin(Path(tempfile.mkdtemp()))), Tool)
    assert manifest_from_plugin(OutilAlert).name == "alert"


def test_run_leve_emet_dedup(tmp_path: Path) -> None:
    with _magasin(tmp_path) as magasin:
        outil = _outil(tmp_path, magasin)
        ctx = Context(store=magasin, domain="code")
        premier = outil.run(ctx, {})
        assert premier.status is Status.OK
        assert premier.payload["levees"] != [] and premier.payload["emises"] != []
        lignes = (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lignes) == len(premier.payload["emises"])
        assert json.loads(lignes[0])["severite"] in ("info", "avertissement", "critique")
        second = outil.run(ctx, {})
        assert second.payload["levees"] == [] and second.payload["emises"] == []  # dédup
        assert (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").strip().split("\n") == lignes


def test_egress_coupe_degrade_local_conserve(tmp_path: Path) -> None:
    with _magasin(tmp_path) as magasin:
        outil = _outil(tmp_path, magasin)
        outil._endpoint = "http://127.0.0.1:9/inexistant"
        ctx = Context(store=magasin, domain="code")
        recu = outil.run(ctx, {})
        assert recu.status is Status.DEGRADE
        assert any("egress" in m for m in recu.payload["degrade"])
        assert (tmp_path / "alerts.jsonl").exists()  # locale conservée


def test_boucle_p1_alerte(tmp_path: Path) -> None:
    from evidra.boucle import Boucle
    from evidra.kernel.scheduler import Budgets, Scheduler

    with _magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        outil = _outil(tmp_path, magasin)
        ctx = Context(store=magasin, domain="code")
        boucle = Boucle(
            domaine="code",
            ordonnanceur=Scheduler(Budgets(max_tool_calls=6)),
            magasin=magasin,
            registres=registres,
            outils={"alert": lambda: outil.run(ctx, {})},
            alerteur=lambda: ("nouveautes",),
        )
        rapport = boucle.tick()
        assert rapport.selection and rapport.selection[0].name == "P1"
        assert any(r.niveau.name == "P1" and r.resultat.status is Status.OK for r in rapport.recus)


def test_demarrage_cable_alerte(tmp_path: Path) -> None:
    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
                "monitoring": {"alert_on_new_relation_involving": ["ransomware"]},
            }
        ),
        encoding="utf-8",
    )
    rapport = demarrer(data_dir=data, directive_path=directive)
    try:
        assert rapport.alert is not None
        assert "alert" in rapport.boucle._outils if rapport.boucle is not None else False
    finally:
        assert rapport.magasin is not None
        rapport.magasin.close()
