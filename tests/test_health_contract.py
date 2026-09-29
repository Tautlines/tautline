"""Quality rec #1 (customer-outcome health contract) + rec #15 (external side-effect delivery proof).

The Private Product A headline journey was 100% down while /healthcheck returned 200, and customer confirmation
emails were "sent" only as outbox rows that never reached a provider. Both gates make "green" mean a
real customer outcome: a milestone-close deploy target must declare a NON-proxy customer-outcome signal
(#1), and any declared outbound side-effect must carry a provider-RECEIPT proof, not an outbox row (#15).
"""

import pytest


def _target(**kw):
    base = {"name": "prod", "milestoneClose": True, "target": "aws", "procedure": "deploy", "healthCheck": "GET /healthcheck returns 200"}
    base.update(kw)
    return base


def _data(targets, health="block", side="block"):
    return {"deploymentTargets": targets, "healthContract": {"enforcement": health}, "sideEffectProof": {"enforcement": side}}


# --- rec #1: health contract ---------------------------------------------------------------------


def test_normalize_health_contract(cli):
    with pytest.raises(SystemExit):
        cli.normalize_health_contract({"healthContract": {"enforcement": "loud"}})
    assert cli.normalize_health_contract({})["enforcement"] == "off"


# --- rec #15: side-effect delivery proof ---------------------------------------------------------


def test_normalize_side_effect_proof(cli):
    with pytest.raises(SystemExit):
        cli.normalize_side_effect_proof({"sideEffectProof": {"enforcement": "loud"}})
    assert cli.normalize_side_effect_proof({})["enforcement"] == "off"
