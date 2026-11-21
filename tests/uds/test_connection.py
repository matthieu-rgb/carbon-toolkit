# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the UDS client connection layer."""
from __future__ import annotations

import time

import pytest

from carbon.uds.connection import (
    UdsConnectionError,
    UdsError,
    UdsTimeoutError,
    open_uds_client,
    uds_errors,
)


def test_request_without_responder_raises_bounded_timeout():
    # virtual bus with no ECU: a UDS request must raise UdsTimeoutError, quickly.
    start = time.monotonic()
    with open_uds_client("carbon-test-uds-noecu", interface="virtual", timeout=0.5) as client:
        with pytest.raises(UdsError):
            with uds_errors("tester_present"):
                client.tester_present()
    assert time.monotonic() - start < 5.0  # bounded, no hang


def test_error_hierarchy():
    assert issubclass(UdsTimeoutError, UdsError)
    assert issubclass(UdsConnectionError, UdsError)


def test_uds_errors_maps_timeout():
    from udsoncan.exceptions import TimeoutException

    with pytest.raises(UdsTimeoutError):
        with uds_errors("probe"):
            raise TimeoutException("no response")


def test_uds_errors_lets_negative_response_propagate():
    from udsoncan.exceptions import NegativeResponseException

    with pytest.raises(NegativeResponseException):
        with uds_errors("probe"):
            raise NegativeResponseException.__new__(NegativeResponseException)
