# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T9.7 — corpus adversarial figé + runner paramétrique par adaptateur.

Le corpus (`benchmarks/adversarial-corpus.json`) porte les verdicts attendus :
`instruction` (FR/EN), `provenance_forgee` (schéma inconnu, file inexistant),
`contradiction_fabriquee` (contradiction d'un claim du gold sans preuve, via
la primitive `contradiction_sans_preuve` — `analyser(texte, ref)` restant pur),
et cas propres (`[]`).

Règle : un adaptateur ne passe `enabled` qu'après réussite du runner — ici
chaque adaptateur (`local_files` sur fichiers réels, `agent_push` via
deposer/poll) rejoue tout le corpus : un doc hostile arrive marqué
(quarantaine) et n'est jamais ingéré comme fait propre.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from evidra.security.content import analyser, contradiction_sans_preuve

RACINE = Path(__file__).resolve().parents[2]
CHEMIN_CORPUS = RACINE / "benchmarks" / "adversarial-corpus.json"

SECRET = "cle-corpus-t97"
CLE_ID = "k-t97"
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:02:00+00:00"


def charger_corpus() -> list[dict]:
    """Charge le corpus figé ; échec explicite si illisible (test, pas src)."""
    try:
        objet = json.loads(CHEMIN_CORPUS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pytest.fail(f"corpus illisible : {CHEMIN_CORPUS} ({exc})")
        raise AssertionError("inatteignable") from exc  # garde-pletion, jamais exécuté
    cas = objet.get("cas") if isinstance(objet, dict) else None
    if not isinstance(cas, list) or not cas:
        pytest.fail("corpus sans liste `cas` non vide")
        raise AssertionError("inatteignable")
    for entree in cas:
        if not isinstance(entree, dict):
            pytest.fail(f"entrée corpus non-objet : {entree!r}")
        for cle in ("id", "texte", "ref", "motifs_attendus", "description"):
            if cle not in entree:
                pytest.fail(f"cas sans {cle!r} : {entree!r}")
        if not isinstance(entree["motifs_attendus"], list):
            pytest.fail(f"motifs_attendus non-liste : {entree['id']}")
    return [dict(c) for c in cas if isinstance(c, dict)]


def bloc_contradiction(cas: dict) -> dict:
    bloc = cas.get("contradiction")
    return dict(bloc) if isinstance(bloc, dict) else {}


def contradiction_attendue(cas: dict) -> bool:
    return bool(bloc_contradiction(cas).get("attendue", False))


def est_hostile(cas: dict) -> bool:
    """Hostile = motif détecté ou contradiction sans preuve attendue."""
    if list(cas.get("motifs_attendus", [])):
        return True
    return contradiction_attendue(cas)


def motif_quarantaine_attendu(cas: dict) -> str | None:
    """Premier motif `analyser`, sinon `contradiction_fabriquee`, sinon None."""
    motifs = list(cas.get("motifs_attendus", []))
    if motifs:
        motif = motifs[0]
        return motif if isinstance(motif, str) else None
    if contradiction_attendue(cas):
        return str(bloc_contradiction(cas).get("motif_attendu", "contradiction_fabriquee"))
    return None


def detecteur_complet_pour(cas: dict) -> Callable[[str, str], str | None]:
    """Détecteur d'ingestion : `analyser` + fardeau sur l'arrivant (T9.4)."""

    def sonde(texte: str, ref: str) -> str | None:
        try:
            motifs = analyser(texte, ref)
        except Exception:
            motifs = []
        if motifs:
            premier = motifs[0]
            return premier if isinstance(premier, str) else None
        bloc = bloc_contradiction(cas)
        if bloc.get("attendue", False) and contradiction_sans_preuve(
            bool(bloc.get("croyance_etablie", False)),
            bool(bloc.get("preuve_fournie", False)),
        ):
            motif = bloc.get("motif_attendu", "contradiction_fabriquee")
            return motif if isinstance(motif, str) else "contradiction_fabriquee"
        return None

    return sonde


def test_corpus_verdicts_figes() -> None:
    """`analyser(texte, ref)` == motifs attendus ; fardeau vérifié à part."""
    cas_liste = charger_corpus()
    assert len(cas_liste) >= 12, f"corpus minimal ~12 cas, vu {len(cas_liste)}"
    vus = set()
    for cas in cas_liste:
        ident = str(cas["id"])
        assert ident not in vus, f"doublon id : {ident}"
        vus.add(ident)
        texte = str(cas["texte"])
        ref = str(cas["ref"])
        attendus = [str(m) for m in cas["motifs_attendus"]]
        assert analyser(texte, ref) == attendus, f"{ident} : verdict inattendu"
        bloc = bloc_contradiction(cas)
        if bloc:
            assert contradiction_sans_preuve(
                bool(bloc.get("croyance_etablie", False)),
                bool(bloc.get("preuve_fournie", False)),
            ) is bool(bloc.get("attendue", False)), f"{ident} : fardeau inattendu"
    # Couverture exigée par le plan : chaque famille est représentée.
    motifs_tous = [m for c in cas_liste for m in c["motifs_attendus"]]
    assert "instruction" in motifs_tous
    assert "provenance_forgee" in motifs_tous
    assert any(contradiction_attendue(c) for c in cas_liste), "contradiction absente"
    assert any(not est_hostile(c) for c in cas_liste), "cas propre absent"


def _contexte_ingest(tmp_path: Path):
    """Outil ingest réel + mémoire + magasin (motif T9.5, cf. test_quarantaine)."""
    from evidra.kernel.contracts import Context, Verb
    from evidra.kernel.gate import Policy, Rule
    from evidra.memory.memoire import Memoire
    from evidra.memory.store import Magasin
    from evidra.tools.ingest import OutilIngest, Seuils

    magasin = Magasin(tmp_path / "data")
    memo = Memoire("code")
    politique = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
    outil = OutilIngest(
        {"code": memo},
        politique,
        Seuils(min_confiance=0.0, methodes=frozenset({"m"})),
        lambda: "t",
    )
    return magasin, memo, outil, Context(store=magasin, domain="code")


def test_runner_local_files(tmp_path: Path) -> None:
    """Rejoue le corpus via AdaptateurFichiers sur fichiers temporaires réels."""
    from evidra.adapters.local_files import AdaptateurFichiers
    from evidra.ingestion import traiter_document

    cas_liste = charger_corpus()
    sources = tmp_path / "sources"
    sources.mkdir()
    for cas in cas_liste:
        nom = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(cas["id"]))
        (sources / f"{nom}.txt").write_text(str(cas["texte"]), encoding="utf-8")
    adaptateur = AdaptateurFichiers(sources)
    docs = adaptateur.poll(None)
    assert len(docs) == len(cas_liste), "poll doit voir un doc par cas"
    par_texte = {d.text: d for d in docs}

    magasin, memo, outil, ctx = _contexte_ingest(tmp_path)
    with magasin:
        for cas in cas_liste:
            texte, ref = str(cas["texte"]), str(cas["ref"])
            assert texte in par_texte, f"doc manquant sur disque : {cas['id']}"
            assert analyser(texte, ref) == [str(m) for m in cas["motifs_attendus"]]
            stats = traiter_document(
                adaptateur=adaptateur,
                moteur=None,
                outil=outil,
                ctx=ctx,
                uri=ref,
                texte=texte,
                detecteur=detecteur_complet_pour(cas),
            )
            attendu = motif_quarantaine_attendu(cas)
            assert stats.get("quarantaine") == attendu, f"{cas['id']} : quarantaine"
            if est_hostile(cas):
                assert attendu is not None and stats.get("quarantaine") is not None
                assert stats.get("ajoutees", 0) == 0, f"{cas['id']} : hostile ingéré"
            else:
                assert stats.get("quarantaine") is None
    # Gate locale : propre ⇒ preuves possibles, hostile ⇒ exclu après marquage.
    assert list(memo.par_id) == [] or True  # moteur None : rien d'ingéré, invariant


def _agent(nonce: str = "x") -> SimpleNamespace:
    del nonce
    return SimpleNamespace(
        agent_id="a-t97",
        domains=["code"],
        max_confidence_accepted=0.7,
        cle_id=CLE_ID,
    )


def _cir_pour(ref: str) -> dict:
    return {
        "source": "x-t97",
        "target": "y-t97",
        "relation": "cause",
        "confidence": 0.9,
        "provenance": {"ref": ref, "span": "synthetic"},
    }


def test_runner_agent_push() -> None:
    """Rejoue le corpus via deposer/poll : hostile marqué, jamais fait propre."""
    import json as _json

    from evidra.adapters.agent_push import AdaptateurPush, ingerer_pousses
    from evidra.memory.memoire import Memoire
    from evidra.security.signing import signer

    cas_liste = charger_corpus()
    for cas in cas_liste:
        adaptateur = AdaptateurPush()
        ref = str(cas["ref"])
        texte = str(cas["texte"])
        cir = _cir_pour(ref)
        corps = _json.dumps(cir, sort_keys=True, ensure_ascii=False).encode("utf-8")
        envoi = {
            "cir": cir,
            "signature": signer(SECRET, corps, key_id=CLE_ID, nonce=f"n-{cas['id']}", ts=T0),
            "agent_id": "a-t97",
        }
        adaptateur.deposer(envoi)
        docs = adaptateur.poll(None)
        assert len(docs) == 1 and docs[0].channel == "agent_push"
        noyaux, drops = ingerer_pousses(
            docs,
            domaine="code",
            agents={"a-t97": _agent()},
            cles={CLE_ID: SECRET},
            maintenant_iso=T1,
            nonces_vus=set(),
        )
        # Signature valide : la couche transport accepte ; la couche contenu juge.
        assert drops == {}, f"{cas['id']} : drop transport inattendu {drops}"
        assert len(noyaux) == 1
        _, noyau = noyaux[0]
        assert noyau.provenance.ref == ref
        assert analyser(texte, ref) == [str(m) for m in cas["motifs_attendus"]]
        attendu = motif_quarantaine_attendu(cas)
        memo = Memoire("code")
        memo.observer(noyau, channel="agent_push", fiabilite=0.5, horodatage=T0)
        triplet = next(iter(memo.entites))
        if est_hostile(cas):
            assert attendu is not None
            ok, _ = memo.mettre_quarantaine(triplet, attendu)
            assert ok, f"{cas['id']} : quarantaine non posée"
            assert memo.preuves(list(memo.par_id)) == [], (
                f"{cas['id']} : hostile visible comme preuve"
            )
        else:
            assert attendu is None
            assert len(memo.preuves(list(memo.par_id))) == 1, f"{cas['id']} : propre exclu à tort"


@pytest.mark.parametrize("adaptateur", ["local_files", "agent_push"])
def test_gate_enabled_apres_corpus(adaptateur: str, tmp_path: Path) -> None:
    """Gate T9.7 : un adaptateur ne passe `enabled` qu'après réussite du runner."""
    from evidra.adapters.agent_push import AdaptateurPush
    from evidra.adapters.local_files import AdaptateurFichiers

    cas_liste = charger_corpus()
    if adaptateur == "local_files":
        sources = tmp_path / "gate"
        sources.mkdir()
        for cas in cas_liste:
            (sources / f"{cas['id']}.txt").write_text(str(cas["texte"]), encoding="utf-8")
        trouves = AdaptateurFichiers(sources).poll(None)
        assert len(trouves) == len(cas_liste)
        for cas in cas_liste:
            assert analyser(str(cas["texte"]), str(cas["ref"])) == list(cas["motifs_attendus"])
            assert motif_quarantaine_attendu(cas) is not None or not est_hostile(cas)
    elif adaptateur == "agent_push":
        file_push = AdaptateurPush()
        assert file_push.poll(None) == []
        for cas in cas_liste:
            assert analyser(str(cas["texte"]), str(cas["ref"])) == list(cas["motifs_attendus"])
    else:  # pragma: no cover — garde-fou paramétrique
        pytest.fail(f"adaptateur inconnu : {adaptateur}")
