# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.1 — worker : valeur, timeout, timeout invalide."""

from __future__ import annotations

import time

import pytest

from evidra.engine_bridge.travailleur import WorkerTimeout, lancer


def test_lancer_retourne_valeur() -> None:
    assert lancer(lambda: 42, 5.0) == 42


def test_lancer_timeout() -> None:
    with pytest.raises(WorkerTimeout):
        lancer(lambda: time.sleep(0.5), 0.01)


def test_lancer_timeout_invalide() -> None:
    with pytest.raises(ValueError):
        lancer(lambda: 1, 0.0)
