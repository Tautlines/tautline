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

def test_proxy_only_signal_is_proxy(cli):
    assert cli.health_signal_is_proxy("GET /healthcheck returns 200")
    assert cli.health_signal_is_proxy("a DB read succeeds")
    assert not cli.health_signal_is_proxy("guest places an order and it appears in the admin list")


def test_milestone_close_without_real_signal_flagged(cli, tmp_path):
    issues = cli.health_contract_issues(_data([_target(outcomeSignals=[])]), tmp_path)
    assert len(issues) == 1 and "non-proxy customer-outcome signal" in issues[0]


def test_only_proxy_signals_flagged(cli, tmp_path):
    issues = cli.health_contract_issues(_data([_target(outcomeSignals=["/health returns 200", "DB ping ok"])]), tmp_path)
    assert len(issues) == 1


def test_real_signal_passes(cli, tmp_path):
    t = _target(outcomeSignals=["guest places an order -> 201 and the order is visible"])
    assert cli.health_contract_issues(_data([t]), tmp_path) == []


def test_non_milestone_target_ignored(cli, tmp_path):
    assert cli.health_contract_issues(_data([_target(milestoneClose=False, outcomeSignals=[])]), tmp_path) == []


def test_health_contract_off_is_silent(cli, tmp_path):
    assert cli.health_contract_issues(_data([_target(outcomeSignals=[])], health="off"), tmp_path) == []


def test_normalize_health_contract(cli):
    with pytest.raises(SystemExit):
        cli.normalize_health_contract({"healthContract": {"enforcement": "loud"}})
    assert cli.normalize_health_contract({})["enforcement"] == "off"


# --- rec #15: side-effect delivery proof ---------------------------------------------------------

def test_side_effect_without_proof_flagged(cli, tmp_path):
    t = _target(outcomeSignals=["x places order ok"], sideEffects=[{"type": "email"}])
    issues = cli.side_effect_proof_issues(_data([t]), tmp_path)
    assert len(issues) == 1 and "provider-receipt proof" in issues[0]


def test_side_effect_outbox_proof_rejected(cli, tmp_path):
    t = _target(outcomeSignals=["x ok"], sideEffects=[{"type": "email", "receiptProof": "an outbox row is written"}])
    assert len(cli.side_effect_proof_issues(_data([t]), tmp_path)) == 1


def test_side_effect_provider_receipt_passes(cli, tmp_path):
    t = _target(outcomeSignals=["x ok"], sideEffects=[{"type": "email", "receiptProof": "SendGrid delivery webhook confirms 'delivered' for the test address"}])
    assert cli.side_effect_proof_issues(_data([t]), tmp_path) == []


def test_side_effect_off_is_silent(cli, tmp_path):
    t = _target(outcomeSignals=["x ok"], sideEffects=[{"type": "email"}])
    assert cli.side_effect_proof_issues(_data([t], side="off"), tmp_path) == []


def test_normalize_side_effect_proof(cli):
    with pytest.raises(SystemExit):
        cli.normalize_side_effect_proof({"sideEffectProof": {"enforcement": "loud"}})
    assert cli.normalize_side_effect_proof({})["enforcement"] == "off"
