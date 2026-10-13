# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Rétention et effacement (T9.10, §17.6) : pur, testé.

Politique par domaine (`retention_jours`) : la tombstone marque, la purge
efface, les deux tracées. Sans politique écrite (`None`), rien n'est purgé.
`candidates()` liste les triplets dont la preuve est périmée
(`last_confirmed_at` + délai < maintenant) ; la purge (tombstone + registre
des suppressions versionné) relève de l'appelant verrouillé (`evidra purger`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def candidates(
    entites: dict[tuple[str, str, str, str], Any],
    *,
    maintenant_iso: str,
    retention_jours: int | None,
) -> list[tuple[str, str, str, str]]:
    """Triplets à purger (preuve périmée) ; `None`/illisible ⇒ `[]`, jamais levée."""
    if retention_jours is None:
        return []
    try:
        maintenant = datetime.fromisoformat(maintenant_iso)
    except (TypeError, ValueError):
        return []
    try:
        delai = int(retention_jours)
    except (TypeError, ValueError):
        return []
    if delai < 1:
        return []
    ciblees = []
    for triplet, env in sorted(entites.items()):
        try:
            date = datetime.fromisoformat(str(env.last_confirmed_at or ""))
        except (TypeError, ValueError):
            continue
        try:
            age_jours = (maintenant - date).total_seconds() / 86400.0  # s/jour (constante physique)
        except TypeError:
            continue
        if age_jours > delai:
            ciblees.append(triplet)
    return ciblees
