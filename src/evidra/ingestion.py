# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Pipeline F1 partagé (T3.8, absorbé par le scheduler en T4.4) : un document.

`poll → phrases → extract → enveloppement (ancre document) → ingest`.
L'ordonnancement (politique, boucle, budgets) relève de T4.x ; ici seule la
plomberie bout-en-bout, avec dépendances explicites injectées.
"""

from __future__ import annotations

import re
from typing import Any

from evidra.engine_bridge.extract import extraire
from evidra.engine_bridge.provenance import envelopper, verifier, vers_noyaux

_SEPARATEUR = re.compile(r"[.!?…\n]+", re.UNICODE)


def decouper_phrases(texte: str) -> list[str]:
    """Segmentation naïve (stdlib) : une phrase = segment non vide."""
    return [s.strip() for s in _SEPARATEUR.split(texte) if s and s.strip()]


def traiter_document(
    *,
    adaptateur: Any,
    moteur: Any,
    outil: Any,
    ctx: Any,
    uri: str,
    texte: str,
    code: bool = False,
    fichier: str = "",
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Ingère un document : stats par étape, jamais levée (comptée)."""
    stats: dict[str, Any] = {
        "phrases": 0,
        "cirs": 0,
        "inverifiables": 0,
        "invalides": 0,
        "ajoutees": 0,
        "confirmees": 0,
        "idempotentes": 0,
        "dropped": {},
    }
    try:
        phrases = decouper_phrases(texte)
        stats["phrases"] = len(phrases)
        if not phrases:
            return stats
        recu_ext = extraire(phrases, moteur=moteur, timeout_s=timeout_s)
        if recu_ext.payload.get("cirs") is None:
            stats["invalides"] += 1
            return stats
        cirs = recu_ext.payload["cirs"]
        stats["cirs"] = len(cirs)
        ancre = adaptateur.etendue(texte, code=code, fichier=fichier)
        noyaux = []
        for cir in cirs:
            try:
                marqueurs = {
                    e[2].get("marker_token")
                    for e in cir.get("edges", [])
                    if isinstance(e, (list, tuple)) and len(e) == 3 and isinstance(e[2], dict)
                }
                spans = {m: ancre for m in marqueurs if m is not None}
                enrichi = envelopper(cir, ref=uri, texte=texte, spans=spans or None)
            except (ValueError, KeyError, TypeError):
                stats["invalides"] += 1
                continue
            if not verifier(enrichi, texte):
                stats["inverifiables"] += 1
                continue
            try:
                noyaux.extend(vers_noyaux(enrichi))
            except ValueError:
                stats["invalides"] += 1
        if not noyaux:
            return stats
        recu = outil.run(ctx, {"noyaux": noyaux, "channel": adaptateur.canal})
        for cle in ("ajoutees", "confirmees", "idempotentes"):
            stats[cle] = int(recu.payload.get(cle, 0))
        for motif, n in dict(recu.payload.get("dropped", {})).items():
            stats["dropped"][motif] = stats["dropped"].get(motif, 0) + int(n)
        stats["trace_ref"] = recu.payload.get("trace_ref")
        return stats
    except Exception as exc:  # noqa: BLE001 — un document n'arrête jamais le flux
        stats["invalides"] += 1
        stats["erreur"] = str(exc)
        return stats
