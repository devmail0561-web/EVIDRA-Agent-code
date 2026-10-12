# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Tests API (T8) : `TestClient` in-process, sockets loopback requises.

Sous `pytest --disable-socket` (job offline I10) : skip explicite, pas
d'échec — le transport ASGI de test ouvre des sockets locales.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if getattr(config.option, "disable_socket", False):
        for item in items:
            item.add_marker(pytest.mark.skip(reason="TestClient exige des sockets (hors I10)"))
