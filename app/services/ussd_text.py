"""Make text safe for USSD: encode to GSM 03.38, and format money without
the cedi sign.

Hubtel (like every USSD network) encodes a message as GSM 7-bit if every
character in it is in the GSM 03.38 alphabet, packing up to 160
characters per message. The moment a single character isn't in that
alphabet -- the cedi sign, a curly quote, an emoji, the Ghanaian letters
written with an open e or open o -- the network has to fall back to a
wider encoding (UCS-2), and the per-message limit drops to about 70
characters. The rest of the message is silently cut, which is exactly
what happened: a confirm screen with the cedi sign in it got cut off
before the voter could see "1. Confirm" / "2. Cancel".

Every piece of text sent to a USSD voter must go through to_gsm7 (or
finalize_ussd_message, which calls it) before it's sent, and every money
amount shown to a voter must come from format_ghs, never format_cedis.
"""

import logging
import unicodedata

logger = logging.getLogger(__name__)

# The GSM 03.38 "basic" character set -- the 127 characters (0-127 minus
# the escape code at 27, which isn't a character on its own) that always
# cost one septet each. This deliberately excludes the "extension table"
# (code 27 followed by one of ^ { } \ [ ] ~ | or the euro sign), which
# costs two septets per character -- see _EXTENSION_CHARS below.
GSM7_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅå"
    "ΔΦΓΛΩΠΨΣΘΞ"
    "ÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
    "_"
)

# These are in the GSM extension table, so each costs the budget of two
# basic characters -- rather than track that double cost through every
# length check, we just never emit them.
_EXTENSION_CHARS = "^{}\\[]~|€"

# Visual lookalikes (and a few genuinely different characters, like the
# Ghanaian open e/open o) that have an exact or close-enough GSM7
# equivalent, so these are replaced outright rather than falling through
# to the accent-stripping/"?" fallback below.
_LOOKALIKE_REPLACEMENTS = {
    "Ɛ": "E", "ɛ": "e",  # open E / open e ("epsilon")
    "Ɔ": "O", "ɔ": "o",  # open O / open o
    "‘": "'", "’": "'", "‚": "'",  # curly single quotes
    "“": '"', "”": '"', "„": '"',  # curly double quotes
    "–": "-", "—": "-",  # en dash, em dash
    "…": "...",  # ellipsis character
    " ": " ",  # non-breaking space
    # The cedi sign itself (U+20B5) -- built with chr() rather than a
    # string literal, so this source file never contains that glyph
    # directly (see the "no cedi sign in source" test). Belt-and-braces:
    # format_ghs never produces it in the first place.
    chr(0x20B5): "GHS ",
}

USSD_MAX_CHARS = 160
# The hard per-message limit, but only true when every character is
# plain GSM7 -- see the module docstring. finalize_ussd_message() only
# truncates against this as a last resort; callers must budget their
# fixed/required text so this never has to cut anything that matters.


def to_gsm7(text):
    """Return text with every character replaced by something in
    GSM7_BASIC: known lookalikes first, then accent-stripping via
    Unicode NFKD, then "?" for anything left over."""
    if not text:
        return text

    for lookalike, replacement in _LOOKALIKE_REPLACEMENTS.items():
        text = text.replace(lookalike, replacement)
    for extension_char in _EXTENSION_CHARS:
        text = text.replace(extension_char, " ")

    result_chars = []
    for char in text:
        if char in GSM7_BASIC:
            result_chars.append(char)
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        base = "".join(c for c in decomposed if c in GSM7_BASIC)
        result_chars.append(base if base else "?")
    return "".join(result_chars)


def is_gsm7(text):
    """True only if every character in text is already in GSM7_BASIC."""
    return all(char in GSM7_BASIC for char in text)


def format_ghs(pesewas):
    """Format a whole number of pesewas as USSD-safe display text, e.g.
    100 -> "GHS 1.00". Always two decimals, integer maths only (never a
    float, which can't represent every pesewas amount exactly).

    Use this for all money shown to a USSD voter. The sibling function
    format_cedis (app/services/pricing.py), which uses the cedi sign, is
    for the website/admin only -- the cedi sign isn't in GSM7_BASIC and
    cuts USSD messages short (see the module docstring)."""
    cedis_whole, remaining_pesewas = divmod(pesewas, 100)
    return f"GHS {cedis_whole}.{remaining_pesewas:02d}"


def finalize_ussd_message(text):
    """Run text through to_gsm7, then enforce USSD_MAX_CHARS as a last
    resort. Callers are responsible for budgeting their message so a
    required line is never the part that gets cut -- this only guards
    against that budgeting being wrong, and logs when it had to step in
    (length only, never the message text itself, which may contain a
    voter's own input)."""
    converted = to_gsm7(text)
    if len(converted) > USSD_MAX_CHARS:
        logger.warning(
            "USSD message exceeded USSD_MAX_CHARS after GSM7 conversion (length=%d)",
            len(converted),
        )
        converted = converted[:USSD_MAX_CHARS]
    return converted
