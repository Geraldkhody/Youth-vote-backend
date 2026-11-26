"""Voting open/closed logic -- pure functions, no database access.

Takes a VotingSettings instance and a `now` so callers (and tests) control
the current time explicitly, instead of this module reaching for
datetime.now() itself.
"""


def is_voting_open(settings, now):
    """True only if voting isn't paused, both dates are set, and `now`
    falls within the window -- on or after voting_opens_at, and strictly
    before voting_closes_at.

    If either date is missing, voting is not open (there's no window to be
    "within" yet).
    """
    if settings.voting_paused:
        return False
    if settings.voting_opens_at is None or settings.voting_closes_at is None:
        return False

    return settings.voting_opens_at <= now < settings.voting_closes_at


def voting_state(settings, now):
    """One of "not_scheduled", "upcoming", "open", "paused", "closed",
    describing the voting window relative to `now`.

    "paused" takes priority over everything else -- even if `now` falls
    inside the open window, a paused vote reports "paused", not "open".
    """
    if settings.voting_opens_at is None or settings.voting_closes_at is None:
        return "not_scheduled"

    if settings.voting_paused:
        return "paused"

    if now < settings.voting_opens_at:
        return "upcoming"

    if now < settings.voting_closes_at:
        return "open"

    return "closed"
