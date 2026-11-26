import pytest

from app.services.pricing import calculate_vote_amount, format_cedis, pesewas_to_cedis
from app.services.voting_settings import cedis_to_pesewas


def test_one_vote_at_100():
    assert calculate_vote_amount(1, 100) == 100


def test_five_votes_at_150():
    assert calculate_vote_amount(5, 150) == 750


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "abc"])
def test_invalid_quantities_are_refused(quantity):
    with pytest.raises(ValueError):
        calculate_vote_amount(quantity, 100)


def test_huge_quantity_is_refused_cleanly():
    # A quantity whose amount would overflow a signed 64-bit integer.
    with pytest.raises(ValueError):
        calculate_vote_amount(2**62, 100)


def test_format_cedis_one_cedi():
    assert format_cedis(100) == "GH₵1.00"


def test_format_cedis_five_cedis_eight_pesewas():
    assert format_cedis(508) == "GH₵5.08"


def test_pesewas_to_cedis_round_trips_exactly_for_every_amount_up_to_100000():
    # cedis_to_pesewas (app/services/voting_settings.py) is the reverse
    # conversion -- every amount here must survive the round trip through
    # a JSON-serialisable float and back without drifting by a pesewa.
    for pesewas in range(1, 100_001):
        price = pesewas_to_cedis(pesewas)
        assert cedis_to_pesewas(price) == pesewas
