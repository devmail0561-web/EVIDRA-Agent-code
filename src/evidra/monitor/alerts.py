# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Décision d'émission d'alertes (T7.2) : dédup par clé + fenêtre, pur.

`doit_emettre` tranche sans E/S : jamais levée, jamais émise, ou dernier
envoi hors fenêtre (et alerte non acquittée — l'acquittement vit dans
`Registres`, lu par l'appelant). L'envoi (JSONL local, egress best-effort)
relève de l'outil `alert`, pas d'ici.
"""

from __future__ import annotations

from datetime import datetime


def doit_emettre(
    dernier_envoi_iso: str | None,
    *,
    maintenant_iso: str,
    fenetre_s: int,
    acquittee: bool = False,
) -> bool:
    """Vrai si l'alerte doit (ré)être émise ; jamais levée (I12)."""
    if acquittee:
        return False
    if not dernier_envoi_iso:
        return True
    try:
        dernier = datetime.fromisoformat(dernier_envoi_iso)
        maintenant = datetime.fromisoformat(maintenant_iso)
        age = (maintenant - dernier).total_seconds()
    except (TypeError, ValueError):
        return True
    return age >= max(0, fenetre_s)
