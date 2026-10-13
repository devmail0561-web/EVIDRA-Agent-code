# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Signatures inter-agents (T9.2) : HMAC-SHA256, nonces, rotation — pur, stdlib.

Enveloppe `signature: {algo, key_id, nonce, ts}` ; fenêtre d'acceptation
5 min, nonce vu = rejet ; une clé par agent (jamais partagée, fichier
0600 + env, jamais repo/logs — cf. runbook). Rejet fail-closed AVANT
toute inspection du contenu : non signé, algorithme hors liste, clé
inconnue/révoquée, HMAC invalide, nonce rejoué, hors fenêtre = 4+ motifs
distincts testés. Rotation : `cibles_rotation()` (reclassement EN RÉVISION).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Any

ALGO = "hmac-sha256"  # spec T9.2/ADR-0009 : mono-opérateur (Ed25519 au 2e opérateur)
ALGOS_AUTORISES = frozenset({ALGO})
FENETRE_S = 300


def signer(secret: str, corps: bytes, *, key_id: str, nonce: str, ts: str) -> dict[str, str]:
    """Construit l'enveloppe signature (émetteur pair)."""
    sig = hmac.new(secret.encode("utf-8"), corps, hashlib.sha256).hexdigest()
    return {"algo": ALGO, "key_id": key_id, "nonce": nonce, "ts": ts, "hmac": sig}


def verifier(
    cles: dict[str, str],
    revoquees: set[str],
    signature: Any,
    corps: bytes,
    *,
    maintenant_iso: str,
    nonces_vus: set[str],
    fenetre_s: int = FENETRE_S,
) -> tuple[bool, str]:
    """`(ok, motif)` : fail-closed, contenu jamais inspecté ici."""
    if not isinstance(signature, dict):
        return False, "non_signé"
    algo = signature.get("algo")
    if algo not in ALGOS_AUTORISES:
        return False, "algorithme_inconnu"
    key_id = signature.get("key_id")
    if not isinstance(key_id, str) or not key_id:
        return False, "cle_absente"
    if key_id in revoquees:
        return False, "cle_revoquee"
    secret = cles.get(key_id)
    if secret is None:
        return False, "cle_inconnue"
    nonce = signature.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return False, "nonce_absent"
    if nonce in nonces_vus:
        return False, "nonce_rejoue"
    try:
        ts = datetime.fromisoformat(str(signature.get("ts", "")))
        maintenant = datetime.fromisoformat(maintenant_iso)
        age = abs((maintenant - ts).total_seconds())
    except (TypeError, ValueError):
        return False, "ts_illisible"
    if age > fenetre_s:
        return False, "hors_fenetre"
    attendu = hmac.new(secret.encode("utf-8"), corps, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(attendu, str(signature.get("hmac", ""))):
        return False, "hmac_invalide"
    nonces_vus.add(nonce)
    return True, "ok"


def cibles_rotation(
    entites: dict[tuple[str, str, str, str], Any],
    *,
    canal: str,
    depuis_iso: str,
) -> list[tuple[str, str, str, str]]:
    """Triplets du canal à reclasser EN RÉVISION (rotation de clé, T9.2)."""
    try:
        depuis = datetime.fromisoformat(depuis_iso)
    except (TypeError, ValueError):
        return []
    cibles = []
    for triplet, env in sorted(entites.items()):
        if getattr(env, "ingest_channel", "") != canal:
            continue
        try:
            date = datetime.fromisoformat(str(env.last_confirmed_at or ""))
        except (TypeError, ValueError):
            continue
        try:
            if date >= depuis:
                cibles.append(triplet)
        except TypeError:
            continue
    return cibles
