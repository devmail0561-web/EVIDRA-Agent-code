# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Authentification API (T8.3) : jetons porteurs + directive signée, stdlib.

Jeton : `Authorization: Bearer <secret>`, comparé en temps constant sur
l'empreinte SHA-256 (secret jamais stocké). Sans jetons configurés :
routes ouvertes (dev/dogfood, documenté). Directive : HMAC-SHA256 du
JSON canonique (`X-Signature: <key_id>:<hex>`), clé owner hors repo.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from evidra.kernel.contracts import Verb


def empreinte_jeton(secret: str) -> str:
    """Empreinte à consigner (le secret ne dort jamais sur disque)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def canonique(directive: dict[str, Any]) -> bytes:
    """JSON canonique signé (trié, compact, UTF-8)."""
    return json.dumps(directive, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def signer(cle: str, corps: bytes) -> str:
    """HMAC-SHA256 hex."""
    return hmac.new(cle.encode("utf-8"), corps, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class Autheur:
    """Vérificateur construit depuis `Directive.api` (immuable, thread-safe)."""

    empreintes: tuple[tuple[str, str, frozenset[Verb]], ...]
    cles: tuple[tuple[str, str], ...]

    def _cherche(self, secret: str) -> tuple[str, frozenset[Verb]] | None:
        digest = empreinte_jeton(secret)
        trouve: tuple[str, frozenset[Verb]] | None = None
        for nom, empreinte, verbes in self.empreintes:
            if hmac.compare_digest(empreinte, digest):
                trouve = (nom, verbes)
        return trouve

    def verbes_jeton(self, secret: str) -> frozenset[Verb] | None:
        """Verbes liés, `None` si inconnu (temps constant)."""
        trouve = self._cherche(secret)
        return trouve[1] if trouve is not None else None

    def nom_jeton(self, secret: str) -> str | None:
        """Nom lié, `None` si inconnu (temps constant, pour le WAL)."""
        trouve = self._cherche(secret)
        return trouve[0] if trouve is not None else None

    def verifier_signature(self, cle_id: str, corps: bytes, signature: str) -> bool:
        """HMAC valide pour `cle_id` ? (temps constant, inconnue ⇒ False)."""
        for ident, secret in self.cles:
            if hmac.compare_digest(ident, cle_id):
                return hmac.compare_digest(signer(secret, corps), signature)
        return False

    def autorise(self, secret: str | None, requis: Collection[Verb]) -> str:
        """`ok` | `anonyme` (401) | `interdit` (403)."""
        if secret is None:
            return "anonyme"
        verbes = self.verbes_jeton(secret)
        if verbes is None:
            return "anonyme"
        return "ok" if any(v in verbes for v in requis) else "interdit"


def autheur_depuis_directive(directive: Any) -> Autheur | None:
    """`None` si aucun jeton (mode ouvert documenté), sinon `Autheur`."""
    api = getattr(directive, "api", None)
    jetons = getattr(api, "jetons", []) or []
    if not jetons:
        return None
    return Autheur(
        empreintes=tuple((j.nom, j.empreinte, frozenset(j.verbes)) for j in jetons),
        cles=tuple((k, v) for k, v in (getattr(api, "cles_directive", {}) or {}).items()),
    )
