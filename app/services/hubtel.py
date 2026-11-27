import json
import re
from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models.hubtel_log import HubtelLog

# Stored bodies are capped at 20 KB (see HubtelLog). Anything bigger is
# truncated so one oversized request can't fill the table or the database
# row size limit.
MAX_BODY_BYTES = 20 * 1024

# Matches a run of 9-15 digits, which covers the phone number formats
# Hubtel's "Mobile" field uses (e.g. "233200585542"). We match on shape
# rather than a specific field name so a phone number buried in a nested
# field doesn't slip through unmasked.
PHONE_PATTERN = re.compile(r"^\d{9,15}$")


def _mask_value(value):
    if isinstance(value, str) and PHONE_PATTERN.match(value):
        return "*" * (len(value) - 3) + value[-3:]
    if isinstance(value, dict):
        return {key: _mask_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    return value


def mask_phone_numbers(body):
    """Mask phone-number-like strings anywhere in a request body, keeping
    only the last 3 digits, before it's ever written to the log table."""
    return _mask_value(body)


def _cap_to_max_size(masked_body):
    serialized = json.dumps(masked_body)
    if len(serialized.encode("utf-8")) <= MAX_BODY_BYTES:
        return masked_body

    # Oversized: store a truncated string instead of the full structure,
    # clearly flagged so nobody mistakes it for the complete request.
    return {
        "_truncated": True,
        "_original_length": len(serialized),
        "body": serialized[:MAX_BODY_BYTES],
    }


def get_client_ip(request):
    """The client IP to trust for one request.

    By default this is the real TCP peer (request.remote_addr) -- the one
    thing a caller can't fake. Only when HUBTEL_TRUST_PROXY_HEADERS is
    explicitly turned on (because we know we're behind a reverse proxy
    that sets it) do we instead read X-Forwarded-For, taking its leftmost
    address. See config.py's comment on HUBTEL_FULFILMENT_ALLOWED_IPS for
    why getting this wrong is dangerous -- trusting that header when
    there's no proxy in front of us would let anyone claim any IP.
    """
    if current_app.config.get("HUBTEL_TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr


def store_hubtel_log(kind, raw_body, response_status, source_ip=None):
    """Save one Hubtel request/response pair to the test-period log.

    This log is for the test period only -- it must be reviewed and pruned
    before going live (see HubtelLog).
    """
    masked_body = mask_phone_numbers(raw_body or {})
    stored_body = _cap_to_max_size(masked_body)

    log = HubtelLog(
        kind=kind,
        received_at=datetime.now(timezone.utc),
        body=stored_body,
        response_status=response_status,
        source_ip=source_ip,
    )
    db.session.add(log)
    db.session.commit()
    return log
