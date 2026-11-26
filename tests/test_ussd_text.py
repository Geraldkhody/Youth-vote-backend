"""Tests for app/services/ussd_text.py -- GSM7 encoding safety and
USSD-safe money formatting.

See the module docstring there for why this matters: a USSD message
with even one non-GSM7 character gets silently cut at ~70 characters by
the network instead of the normal 160.
"""

import logging

from app.services.ussd_text import (
    USSD_MAX_CHARS,
    finalize_ussd_message,
    format_ghs,
    is_gsm7,
    to_gsm7,
)

OPEN_E_NAME = "Ɛfa Mensah"  # "epsilon" (open E)
OPEN_O_NAME = "Ɔdɔ Boateng"  # open O
CURLY_QUOTES_NAME = "D’Angelo “Jay”"
EMOJI_NAME = "Ama \U0001f600"
CEDI_IN_TEXT = "Cost: ₵1.00"
EM_DASH_TEXT = "Before — after"
TAB_TEXT = "Tab\there"


def test_to_gsm7_handles_open_e_and_open_o_names():
    converted = to_gsm7(OPEN_E_NAME)
    assert is_gsm7(converted)
    assert converted == "Efa Mensah"

    converted = to_gsm7(OPEN_O_NAME)
    assert is_gsm7(converted)
    assert converted == "Odo Boateng"


def test_to_gsm7_handles_curly_quotes():
    converted = to_gsm7(CURLY_QUOTES_NAME)
    assert is_gsm7(converted)
    assert converted == "D'Angelo \"Jay\""


def test_to_gsm7_handles_emoji():
    converted = to_gsm7(EMOJI_NAME)
    assert is_gsm7(converted)
    assert "?" in converted


def test_to_gsm7_handles_cedi_sign():
    converted = to_gsm7(CEDI_IN_TEXT)
    assert is_gsm7(converted)
    assert "₵" not in converted
    assert "GHS" in converted


def test_to_gsm7_handles_em_dash():
    converted = to_gsm7(EM_DASH_TEXT)
    assert is_gsm7(converted)
    assert converted == "Before - after"


def test_to_gsm7_handles_tab():
    converted = to_gsm7(TAB_TEXT)
    assert is_gsm7(converted)


def test_format_ghs_formats_whole_and_fractional_pesewas():
    assert format_ghs(100) == "GHS 1.00"
    assert format_ghs(150) == "GHS 1.50"


def test_format_ghs_large_amount_has_no_float_rounding():
    # 100000000 pesewas = GHS 1,000,000.00 -- a value a float can't
    # always represent exactly; integer divmod must be exact.
    assert format_ghs(100000000) == "GHS 1000000.00"


def test_finalize_ussd_message_converts_to_gsm7():
    message = finalize_ussd_message(CEDI_IN_TEXT)
    assert is_gsm7(message)
    assert "₵" not in message


def test_finalize_ussd_message_truncates_and_logs_without_personal_data(caplog):
    long_message = "x" * (USSD_MAX_CHARS + 20)
    with caplog.at_level(logging.WARNING):
        result = finalize_ussd_message(long_message)

    assert len(result) == USSD_MAX_CHARS
    assert len(caplog.records) == 1
    logged_text = caplog.records[0].getMessage()
    assert long_message not in logged_text  # no message content, personal or not
    assert str(USSD_MAX_CHARS + 20) in logged_text
