# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Adaptateur `agent_push` (T9.3) : CIRs poussés par des agents pairs.

`deposer()` reçoit `{cir, signature, agent_id}` (fil externe, thread-safe) ;
`poll()` les rend en `RawDoc` JSON (canal `agent_push`, jamais d'extraction
moteur : les CIR sont déjà structurés). `ingerer_pousses()` valide
(fail-closed : signature T9.2, domaine autorisé, confiance plafonnée au
`max_confidence_accepted` de l'agent) et rend des `CirCore` pour
`OutilIngest` — entrée systématique en NOUVELLE, canal `agent_push`.
Anti-Sybil : la sortie de quarantaine exige une confirmation non-agent
(`Memoire.observer`, jamais N confirmations pairs).
"""

from __future__ import annotations

import json
import logging
import queue
from collections.abc import Mapping
from typing import Any

from evidra.kernel.contracts import CostHint, Cursor, RawDoc
from evidra.memory.envelope import CirCore, Provenance, span_depuis_dict
from evidra.security.signing import verifier

log = logging.getLogger("evidra.adapters.agent_push")


class AdaptateurPush:
    """File de CIRs pairs (push local) au contrat `Adapter`."""

    name = "agent_push"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"since": {"type": ["string", "null"]}},
    }
    output_schema: Mapping[str, Any] = {"type": "object", "properties": {"docs": {"type": "array"}}}
    cost_hint = CostHint(ms=1.0, calls=1)
    permissions: frozenset = frozenset()
    channels: tuple[str, ...] = ("agent_push",)
    requires_network = False

    def __init__(self, *, canal: str = "agent_push") -> None:
        self.canal = canal
        self._file: queue.Queue[dict[str, Any]] = queue.Queue()
        self._seq = 0

    def deposer(self, envoi: Mapping[str, Any]) -> int:
        """Enfile un envoi `{cir, signature, agent_id}` ; retourne son rang."""
        self._seq += 1
        self._file.put({"seq": self._seq, "envoi": dict(envoi)})
        return self._seq

    def poll(self, since: Cursor | None) -> list[RawDoc]:
        """Vide la file (au-moins-une-fois) ; `since` = curseur opaque."""
        vus = self._charger_curseur(since)
        trouves = []
        while True:
            try:
                item = self._file.get_nowait()
            except queue.Empty:
                break
            if item["seq"] in vus:
                continue
            vus.add(item["seq"])
            trouves.append(
                RawDoc(
                    uri=f"agent://push/{item['seq']}",
                    text=json.dumps(item["envoi"], ensure_ascii=False, sort_keys=True),
                    channel=self.canal,
                    mime="application/x-gcn-push",
                )
            )
        self._etat = vus
        return trouves

    def ack(self, cursor: str) -> None:
        """Marque un curseur (validé, fail-fast)."""
        try:
            objet = json.loads(cursor)
        except ValueError:
            raise ValueError("curseur illisible") from None
        if not isinstance(objet, dict) or not isinstance(objet.get("vus"), list):
            raise ValueError("curseur mal formé")

    def curseur(self) -> str:
        """État courant sérialisé (à persister via les registres, T2.6)."""
        return json.dumps({"vus": sorted(getattr(self, "_etat", set()))}, sort_keys=True)

    def _charger_curseur(self, since: Cursor | None) -> set[int]:
        if since is None:
            return set()
        try:
            objet = json.loads(str(since))
        except ValueError:
            return set()
        vus = objet.get("vus") if isinstance(objet, dict) else None
        return {int(x) for x in vus} if isinstance(vus, list) else set()


def ingerer_pousses(
    docs: list[RawDoc],
    *,
    domaine: str,
    agents: Mapping[str, Any],
    cles: Mapping[str, str],
    revoquees: set[str] | None = None,
    maintenant_iso: str,
    nonces_vus: set[str] | None = None,
) -> tuple[list[tuple[str, CirCore]], dict[str, int]]:
    """Valide des poussées → `(agent_id, CirCore)` ; `(noyaux, drops)` (T9.3).

    `agents` : `agent_id → AgentPair` (domaines, plafond, `cle_id`).
    Agent inconnu, clé absente/vide, domaine refusé, signature rejetée,
    CIR malformé : droppé avec motif, jamais d'exception.
    """
    vus = nonces_vus if nonces_vus is not None else set()
    interdites = revoquees if revoquees is not None else set()
    noyaux: list[tuple[str, CirCore]] = []
    drops: dict[str, int] = {}
    for doc in docs:
        try:
            envoi = json.loads(doc.text)
            if not isinstance(envoi, dict):
                raise ValueError("envoi non-objet")
            agent_id = str(envoi["agent_id"])
            agent = agents[agent_id]
            if not getattr(agent, "cle_id", ""):
                raise ValueError("agent sans clé")
            if domaine not in list(getattr(agent, "domains", [])):
                raise ValueError("domaine refusé")
            corps = json.dumps(envoi["cir"], sort_keys=True, ensure_ascii=False).encode("utf-8")
            ok, motif = verifier(
                cles,
                interdites,
                envoi.get("signature"),
                corps,
                maintenant_iso=maintenant_iso,
                nonces_vus=vus,
            )
            if not ok:
                raise ValueError(motif)
            if not isinstance(envoi.get("signature"), dict):
                raise ValueError("signature non-objet")
            if envoi["signature"].get("key_id") != agent.cle_id:
                raise ValueError("clé étrangère")
            cir = envoi["cir"]
            if not cir["provenance"]["ref"]:
                raise ValueError("ref manquante")
            publie = cir["provenance"].get("published_at")
            noyau = CirCore(
                source=str(cir["source"]),
                target=str(cir["target"]),
                relation=str(cir["relation"]),
                confidence=min(float(cir["confidence"]), float(agent.max_confidence_accepted)),
                provenance=Provenance(
                    ref=str(cir["provenance"]["ref"]),
                    span=span_depuis_dict(cir["provenance"].get("span", "synthetic")),
                    extraction_method=str(cir["provenance"].get("extraction_method", "agent_push")),
                    model_version=str(cir["provenance"].get("model_version", "")),
                    extracted_at=str(cir["provenance"].get("extracted_at", "")),
                    content_sha256=str(cir["provenance"].get("content_sha256", "")),
                    published_at=publie if isinstance(publie, str) else None,
                ),
            )
            noyaux.append((agent_id, noyau))
        except (ValueError, KeyError, TypeError, AttributeError, AssertionError) as exc:
            motif_rejet = str(exc) if str(exc) else "invalide"
            drops[motif_rejet] = drops.get(motif_rejet, 0) + 1
            continue
    return noyaux, drops
