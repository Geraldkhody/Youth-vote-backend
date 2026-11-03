from app.utils import normalize_phone


def test_normalizes_leading_zero_format():
    assert normalize_phone("0241234567") == "233241234567"


def test_normalizes_233_format():
    assert normalize_phone("233241234567") == "233241234567"


def test_normalizes_plus_233_format():
    assert normalize_phone("+233241234567") == "233241234567"


def test_rejects_invalid_phone():
    assert normalize_phone("12345") is None
    assert normalize_phone("0241234") is None
    assert normalize_phone("abcdefghij") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None
