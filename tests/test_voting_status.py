from datetime import datetime, timedelta, timezone

from app.models.voting_settings import VotingSettings
from app.services.voting_status import is_voting_open, voting_state

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
OPENS = NOW - timedelta(days=1)
CLOSES = NOW + timedelta(days=1)


def _settings(**overrides):
    defaults = dict(voting_opens_at=OPENS, voting_closes_at=CLOSES, voting_paused=False)
    defaults.update(overrides)
    return VotingSettings(**defaults)


def test_not_scheduled_when_dates_are_missing():
    settings = _settings(voting_opens_at=None, voting_closes_at=None)
    assert voting_state(settings, NOW) == "not_scheduled"
    assert is_voting_open(settings, NOW) is False


def test_upcoming_before_opens_at():
    settings = _settings(voting_opens_at=NOW + timedelta(hours=1))
    assert voting_state(settings, NOW) == "upcoming"
    assert is_voting_open(settings, NOW) is False


def test_open_between_opens_and_closes():
    settings = _settings()
    assert voting_state(settings, NOW) == "open"
    assert is_voting_open(settings, NOW) is True


def test_exactly_at_opens_at_is_open():
    settings = _settings(voting_opens_at=NOW, voting_closes_at=NOW + timedelta(days=1))
    assert voting_state(settings, NOW) == "open"
    assert is_voting_open(settings, NOW) is True


def test_exactly_at_closes_at_is_closed():
    settings = _settings(voting_opens_at=NOW - timedelta(days=1), voting_closes_at=NOW)
    assert voting_state(settings, NOW) == "closed"
    assert is_voting_open(settings, NOW) is False


def test_closed_after_closes_at():
    settings = _settings(voting_closes_at=NOW - timedelta(hours=1))
    assert voting_state(settings, NOW) == "closed"
    assert is_voting_open(settings, NOW) is False


def test_paused_overrides_open():
    settings = _settings(voting_paused=True)
    assert voting_state(settings, NOW) == "paused"
    assert is_voting_open(settings, NOW) is False
