# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Cale de compatibilité : réexporte `engine_bridge.essai` (référence unique)."""

from __future__ import annotations

from evidra.engine_bridge.essai import moteur_essai, parseur_essai

__all__ = ["moteur_essai", "parseur_essai"]
