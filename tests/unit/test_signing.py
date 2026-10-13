# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T9.2 — signatures : 4+ rejets distincts, happy path, rotation."""

from __future__ import annotations

from evidra.security.signing import cibles_rotation, signer, verifier

T0 = "2026-01-01T00:02:00+00:00"


def _sig(**champs):
    base = signer("s3cr3t", b"corps", key_id="a1", nonce="n1", ts="2026-01-01T00:00:00+00:00")
    base.update(champs)
    return base


def _motif(sig, corps=b"corps", t0=T0, cles=None, revoquees=None) -> str:
    return verifier(
        {"a1": "s3cr3t"} if cles is None else cles,
        set() if revoquees is None else revoquees,
        sig,
        corps,
        maintenant_iso=t0,
        nonces_vus=set(),
    )[1]


def test_valide_et_nonce_enregistre() -> None:
    vus: set[str] = set()
    ok, motif = verifier(
        {"a1": "s3cr3t"}, set(), _sig(), b"corps", maintenant_iso=T0, nonces_vus=vus
    )
    assert (ok, motif) == (True, "ok") and vus == {"n1"}
    rejou = verifier({"a1": "s3cr3t"}, set(), _sig(), b"corps", maintenant_iso=T0, nonces_vus=vus)
    assert rejou == (False, "nonce_rejoue")
    assert _motif(None) == "non_signé"


def test_quatre_rejets_distincts() -> None:
    assert _motif(_sig(algo="rsa")) == "algorithme_inconnu"
    assert _motif(_sig(), revoquees={"a1"}) == "cle_revoquee"
    assert _motif(_sig(), cles={}) == "cle_inconnue"
    assert _motif(_sig(), corps=b"autre") == "hmac_invalide"


def test_fenetre_et_ts() -> None:
    assert _motif(_sig(), t0="2026-01-01T01:00:00+00:00") == "hors_fenetre"
    assert _motif(_sig(ts="pas-une-date")) == "ts_illisible"
    assert _motif(_sig(nonce="")) == "nonce_absent"


def test_rotation_cible() -> None:
    class _Env:
        def __init__(self, canal, date):
            self.ingest_channel = canal
            self.last_confirmed_at = date

    entites = {
        ("d", "a", "cause", "b"): _Env("agent_push", "2026-02-01T00:00:00+00:00"),
        ("d", "c", "cause", "d"): _Env("agent_push", "2026-01-01T00:00:00+00:00"),
        ("d", "e", "cause", "f"): _Env("local_files", "2026-03-01T00:00:00+00:00"),
    }
    assert cibles_rotation(entites, canal="agent_push", depuis_iso="2026-01-15T00:00:00+00:00") == [
        ("d", "a", "cause", "b")
    ]
    assert cibles_rotation(entites, canal="agent_push", depuis_iso="pas-une-date") == []
