from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.attempts import StartAttemptRequest
from app.services.attempt_service import _compute_expires_at, create_attempt


@pytest.mark.parametrize("duration", [60, 900, 28800])
def test_start_attempt_accepts_duration_bounds(duration):
    assert StartAttemptRequest(mock_test_id=1, duration_seconds=duration).duration_seconds == duration


@pytest.mark.parametrize("duration", [0, 59, 28801, -60])
def test_start_attempt_rejects_duration_outside_supported_range(duration):
    with pytest.raises(ValidationError):
        StartAttemptRequest(mock_test_id=1, duration_seconds=duration)


@pytest.mark.parametrize("duration", [0, 59, 28801, -60, 1.5, True])
def test_service_rejects_untrusted_duration_before_database_access(duration):
    with pytest.raises(HTTPException) as error:
        create_attempt(conn=None, requesting_user_id=1, mock_test_id=1, duration_seconds=duration)
    assert error.value.status_code == 422


def test_expiry_is_computed_from_attempt_duration():
    attempt = {"started_at": datetime(2026, 1, 1, 12, 0, 0), "duration_seconds": 2700}
    assert _compute_expires_at(attempt) == "2026-01-01T12:45:00"


def test_legacy_untimed_attempt_has_no_expiry():
    assert _compute_expires_at({"started_at": datetime(2026, 1, 1), "duration_seconds": None}) is None
