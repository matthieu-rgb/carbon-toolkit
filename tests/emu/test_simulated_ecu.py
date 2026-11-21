# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the simulated ISO-TP/UDS ECU, driven by the real UDS client."""
from __future__ import annotations

import itertools

import pytest
from udsoncan.exceptions import NegativeResponseException

from carbon.emu.ecu import EcuConfig, SimulatedEcu
from carbon.uds.connection import open_uds_client
from carbon.uds.seedkey import ExampleSeedKey

_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    """A unique virtual-bus channel per test (no cross-test frame leakage)."""
    return f"carbon-ecu-test-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    """A started SimulatedEcu on a virtual bus; readiness awaited, not slept."""
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()  # start() blocked until the listener was receiving
        yield e


@pytest.fixture
def client(ecu, channel):
    """A udsoncan client on the same virtual channel as the running ECU."""
    with open_uds_client(channel, interface="virtual", timeout=1.0) as c:
        yield c


def _unlock(client):
    client.change_session(0x03)
    seed = client.request_seed(0x01).service_data.seed
    client.send_key(0x02, ExampleSeedKey().key_from_seed(seed))


def test_tester_present_positive(ecu, client):
    # 0x3E 0x00 -> positive (no exception)
    client.tester_present()


def test_read_vin_without_unlock(ecu, client):
    resp = client.read_data_by_identifier(0xF190)
    assert resp.service_data.values[0xF190] == b"CARBONSIMECU00001"


def test_protected_did_denied_when_locked(ecu, client):
    with pytest.raises(NegativeResponseException) as e:
        client.read_data_by_identifier(0x1234)
    assert e.value.response.code == 0x33  # securityAccessDenied


def test_security_access_requires_extended_session(ecu, client):
    # request_seed in default session -> NRC 0x7F serviceNotSupportedInActiveSession
    with pytest.raises(NegativeResponseException) as e:
        client.request_seed(0x01)
    assert e.value.response.code == 0x7F


def test_full_unlock_then_read_protected(ecu, client):
    client.change_session(0x03)
    seed = client.request_seed(0x01).service_data.seed
    assert seed == b"\x11\x22\x33\x44"
    client.send_key(0x02, ExampleSeedKey().key_from_seed(seed))
    resp = client.read_data_by_identifier(0x1234)
    assert resp.service_data.values[0x1234] == b"\xDE\xAD\xBE\xEF"


def test_bad_key_rejected(ecu, client):
    client.change_session(0x03)
    client.request_seed(0x01)
    with pytest.raises(NegativeResponseException) as e:
        client.send_key(0x02, b"\x00\x00\x00\x00")
    assert e.value.response.code == 0x35  # invalidKey


def test_send_key_before_seed_sequence_error(ecu, client):
    client.change_session(0x03)
    with pytest.raises(NegativeResponseException) as e:
        client.send_key(0x02, b"\xAA\xBB\xCC\xDD")
    assert e.value.response.code == 0x24  # requestSequenceError


def test_read_dtc_by_status_mask(ecu, client):
    resp = client.get_dtc_by_status_mask(0xFF)
    dtcs = resp.service_data.dtcs
    assert len(dtcs) == 2
    assert {d.id for d in dtcs} == {0x010203, 0x040506}


def test_read_dtc_mask_filters(ecu, client):
    # status 0x24 matches bit pattern, 0x2F also; a mask hitting only the
    # second DTC (0x2F has bit0 set, 0x24 does not) returns exactly one.
    resp = client.get_dtc_by_status_mask(0x01)
    dtcs = resp.service_data.dtcs
    assert len(dtcs) == 1
    assert dtcs[0].id == 0x040506


def test_clear_dtc_denied_when_locked(ecu, client):
    with pytest.raises(NegativeResponseException) as e:
        client.clear_dtc(0xFFFFFF)
    assert e.value.response.code == 0x33  # securityAccessDenied


def test_clear_dtc_after_unlock_empties_store(ecu, client):
    _unlock(client)
    client.clear_dtc(0xFFFFFF)  # positive
    resp = client.get_dtc_by_status_mask(0xFF)
    assert len(resp.service_data.dtcs) == 0


def test_session_reset_relocks_security(ecu, client):
    _unlock(client)
    assert client.read_data_by_identifier(0x1234).service_data.values[0x1234] == b"\xDE\xAD\xBE\xEF"
    client.change_session(0x01)  # back to default re-locks
    with pytest.raises(NegativeResponseException) as e:
        client.read_data_by_identifier(0x1234)
    assert e.value.response.code == 0x33


def test_state_persists_across_connections(ecu, channel):
    # Unlock on one client connection...
    with open_uds_client(channel, interface="virtual", timeout=1.0) as c1:
        _unlock(c1)
    # ...a brand new connection still sees the ECU unlocked (state lives in the ECU).
    with open_uds_client(channel, interface="virtual", timeout=1.0) as c2:
        assert c2.read_data_by_identifier(0x1234).service_data.values[0x1234] == b"\xDE\xAD\xBE\xEF"
        # Returning to default relocks; the next read is denied again.
        c2.change_session(0x01)
        with pytest.raises(NegativeResponseException) as e:
            c2.read_data_by_identifier(0x1234)
        assert e.value.response.code == 0x33


def test_unknown_service_returns_service_not_supported(ecu, channel):
    # 0x3F is not implemented -> NRC 0x11 serviceNotSupported. Sent raw via the
    # client's underlying connection so udsoncan does not pre-filter it.
    with open_uds_client(channel, interface="virtual", timeout=1.0) as client:
        client.conn.send(b"\x3F\x00")
        payload = client.conn.wait_frame(timeout=1.0)
    assert payload == b"\x7F\x3F\x11"


def test_unknown_did_out_of_range(ecu, client):
    with pytest.raises(NegativeResponseException) as e:
        client.read_data_by_identifier(0x9999)
    assert e.value.response.code == 0x31  # requestOutOfRange


def test_session_bad_subfunction(ecu, client):
    with pytest.raises(NegativeResponseException) as e:
        client.change_session(0x05)
    assert e.value.response.code == 0x12  # subFunctionNotSupported


def test_config_is_frozen_dataclass():
    cfg = EcuConfig()
    assert cfg.req_id == 0x7E0 and cfg.resp_id == 0x7E8
    with pytest.raises(Exception):
        cfg.req_id = 0x123  # frozen


def test_raising_handler_does_not_kill_server(ecu, client, caplog):
    # Make one request handler raise, then prove the listener survived it and
    # still answers a subsequent well-formed request.
    original = ecu._handle_tester_present
    calls = {"n": 0}

    def boom(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("induced handler failure")
        return original(request)

    ecu._handle_tester_present = boom
    with caplog.at_level("ERROR", logger="carbon.emu.ecu"):
        # First tester_present triggers the raise -> no reply -> client times out.
        with pytest.raises(Exception):
            client.tester_present()
        # Server is still alive: a fresh well-formed request is answered.
        assert client.read_data_by_identifier(0xF190).service_data.values[0xF190] == b"CARBONSIMECU00001"
        client.tester_present()  # second call now goes through the real handler
    assert ecu._thread.is_alive()
    assert any("listener error" in r.message for r in caplog.records)


def test_garbage_frame_does_not_kill_server(ecu, channel):
    # An empty/garbage UDS frame must not wedge the listener; a following valid
    # request still gets a correct response.
    with open_uds_client(channel, interface="virtual", timeout=1.0) as client:
        client.conn.send(b"")  # empty PDU -> dispatch returns None, no reply
        assert client.read_data_by_identifier(0xF190).service_data.values[0xF190] == b"CARBONSIMECU00001"
    assert ecu._thread.is_alive()


def test_stop_is_idempotent(channel):
    ecu = SimulatedEcu(channel, interface="virtual")
    ecu.start()
    assert ecu.ready.is_set()
    ecu.stop()
    ecu.stop()  # second stop must not raise
