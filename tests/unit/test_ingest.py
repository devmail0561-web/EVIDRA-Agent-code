# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.6 — ingest : porte, seuils, idempotence, confirmation, dropped, trace."""

from __future__ import annotations

from pathlib import Path

from evidra.kernel.contracts import Context, Status, Tool, Verb
from evidra.kernel.gate import Policy, Rule
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire, appliquer_domaine, memoire_depuis_etat
from evidra.memory.store import Magasin
from evidra.tools.ingest import OutilIngest, Seuils


def _noyau(
    src: str = "Authentification",
    dst: str = "accès",
    ref: str = "doc://1",
    conf: float = 0.87,
    methode: str = "symbolic_rust",
) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=conf,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method=methode,
            model_version="gcn-core-4.0.0",
            extracted_at="t",
        ),
    )


def _outil(magasin: Magasin, domaine: str = "code") -> tuple[OutilIngest, Context]:
    policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
    seuils = Seuils(min_confiance=0.70, methodes=frozenset({"symbolic_rust", "ml_python"}))
    outil = OutilIngest({domaine: Memoire(domaine)}, policy, seuils, lambda: "2026-10-11T00:00:00Z")
    magasin.definir_appliquer(f"domains/{domaine}", appliquer_domaine)
    return outil, Context(store=magasin, domain=domaine)


def test_manifeste_registre_compatible() -> None:
    manifeste = manifest_from_plugin(OutilIngest)
    assert manifeste.name == "ingest" and manifeste.harness_required == "1.0"


def test_outil_conforme_protocole(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        outil, _ctx = _outil(magasin)
        assert isinstance(outil, Tool)


def test_ingest_nouvelle_puis_idempotente(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        outil, ctx = _outil(magasin)
        premier = outil.run(ctx, {"noyaux": [_noyau()], "channel": "test"})
        assert premier.status is Status.OK
        assert premier.payload["ajoutees"] == 1 and premier.payload["trace_ref"] == 1
        second = outil.run(ctx, {"noyaux": [_noyau()], "channel": "test"})
        assert second.payload["idempotentes"] == 1 and second.payload["trace_ref"] is None
        assert second.payload["ajoutees"] == 0
        memo = outil._memoires["code"]
        assert len(memo.entites) == 1 and len(memo.index) == 1


def test_confirmation_deuxieme_ref(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        outil, ctx = _outil(magasin)
        outil.run(ctx, {"noyaux": [_noyau(ref="doc://1")], "channel": "test"})
        recu = outil.run(ctx, {"noyaux": [_noyau(ref="doc://2")], "channel": "test"})
        assert recu.payload["confirmees"] == 1
        assert (
            outil._memoires["code"]
            .entites[("code", "authentification", "cause", "acces")]
            .confirmation_count
            == 2
        )


def test_sous_seuil_et_methode_dropped(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        outil, ctx = _outil(magasin)
        recu = outil.run(
            ctx,
            {
                "noyaux": [_noyau(conf=0.10), _noyau(methode="bidouille"), _noyau()],
                "channel": "test",
            },
        )
        assert recu.status is Status.DEGRADE
        assert recu.payload["dropped"] == {"methode-refusee": 1, "sous-seuil-confiance": 1}
        assert recu.payload["ajoutees"] == 1
        assert len(outil._memoires["code"].entites) == 1


def test_porte_refuse_sans_effet(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        policy = Policy(forbidden=frozenset({Rule("ingest", Verb.INGEST, "*")}))
        seuils = Seuils(min_confiance=0.70, methodes=frozenset({"symbolic_rust"}))
        outil = OutilIngest({"code": Memoire("code")}, policy, seuils, lambda: "t")
        ctx = Context(store=magasin, domain="code")
        recu = outil.run(ctx, {"noyaux": [_noyau()], "channel": "test"})
        assert recu.status is Status.REFUSED
        assert len(outil._memoires["code"].entites) == 0


def test_domaine_inconnu_et_args_invalides(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        outil, ctx = _outil(magasin)
        assert outil.run(ctx, {"noyaux": "pas-une-liste"}).status is Status.FAILED
        assert (
            outil.run(Context(store=magasin, domain="inconnu"), {"noyaux": []}).status
            is Status.FAILED
        )
        recu = outil.run(ctx, {"noyaux": [_noyau(), 42], "channel": "test"})
        assert recu.payload["dropped"] == {"forme-invalide": 1}
        assert recu.payload["ajoutees"] == 1


def test_wal_rejoue_memoire_identique(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        outil, ctx = _outil(magasin)
        outil.run(
            ctx, {"noyaux": [_noyau(ref="doc://1"), _noyau(ref="doc://2")], "channel": "test"}
        )
        magasin.snapshot("domains/code")
    with Magasin(tmp_path) as magasin:
        charge = magasin.recharger("domains/code")
        rebuilt, ignores = memoire_depuis_etat("code", charge.etat)
        assert ignores == 0
        assert len(rebuilt.entites) == 1
        assert (
            rebuilt.entites[("code", "authentification", "cause", "acces")].confirmation_count == 2
        )


def test_plafond_canal_t91() -> None:
    import tempfile
    from pathlib import Path

    from evidra.kernel.contracts import Context, Verb
    from evidra.kernel.gate import Policy, Rule
    from evidra.memory.memoire import Memoire
    from evidra.memory.store import Magasin
    from evidra.tools.ingest import OutilIngest, Seuils

    with Magasin(Path(tempfile.mkdtemp())) as magasin:
        policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
        seuils = Seuils(
            min_confiance=0.0,
            methodes=frozenset({"symbolic_rust"}),
            plafonds={"http_feed": 0.5},
        )
        outil = OutilIngest({"code": Memoire("code")}, policy, seuils, lambda: "t")
        ctx = Context(store=magasin, domain="code")
        recu = outil.run(ctx, {"noyaux": [_noyau(conf=0.99)], "channel": "http_feed"})
        assert recu.status.value == "ok"
        assert recu.payload["plafonnees"] == 1
        assert recu.payload["ajoutees"] == 1
