"""Pure pricing calculations -- no database access, no Flask imports.

Money is stored and calculated as whole pesewas (integer) everywhere in
this codebase -- never float math, which can't represent amounts like
GH₵0.10 exactly, and rounding errors in money math are the kind of bug
that's invisible until it isn't. A GH₵ amount only ever leaves this
integer-pesewas world in two ways: as display text (format_cedis) or as
the decimal-cedis number Hubtel's API requires (pesewas_to_cedis) -- both
built from Decimal arithmetic, never a float calculation.
"""

from decimal import Decimal

# The largest amount (in pesewas) that fits in a signed 64-bit integer,
# which is the database column type used for amount_pesewas later. We
# refuse to calculate anything bigger than this, rather than let it
# silently overflow.
MAX_SIGNED_BIGINT = 2**63 - 1


def calculate_vote_amount(quantity, vote_fee_pesewas):
    """Return the total vote amount in pesewas for `quantity` votes at
    `vote_fee_pesewas` each.

    quantity must be a whole number, at least 1. There's no upper limit on
    quantity itself, but we refuse an amount that wouldn't fit in a signed
    64-bit integer (the database column type), rather than silently
    overflowing or truncating it.
    """
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValueError("quantity must be a whole number")
    if quantity < 1:
        raise ValueError("quantity must be at least 1")

    amount = quantity * vote_fee_pesewas

    if amount > MAX_SIGNED_BIGINT:
        raise ValueError("quantity is too large -- the resulting amount would overflow")

    return amount


def format_cedis(pesewas):
    """Format a whole number of pesewas as display text, e.g. 100 -> "GH₵1.00".

    Always two decimals. This is for display only -- never parse this text
    back into a number; keep using the integer pesewas value for that.
    """
    cedis_whole, remaining_pesewas = divmod(pesewas, 100)
    return f"GH₵{cedis_whole}.{remaining_pesewas:02d}"


def pesewas_to_cedis(pesewas):
    """Convert whole pesewas to a cedis amount for JSON, e.g. 150 -> 1.5.
    Used for Hubtel's AddToCart "Price" field, which must be a decimal
    number of cedis, not pesewas.

    The conversion itself is Decimal arithmetic (never float) -- only the
    very last step converts to float, because that's what json.dumps can
    serialise as a JSON number (a Decimal isn't). At this scale (at most 2
    decimal places), that conversion round-trips back to the exact same
    pesewas value every time -- see cedis_to_pesewas in
    app/services/voting_settings.py, and the round-trip test for this
    function in tests/test_pricing.py.
    """
    return float(Decimal(pesewas) / Decimal(100))
