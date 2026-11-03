import random

from app.models.nominee import Nominee

MAX_ATTEMPTS = 200


class CodeGenerationError(Exception):
    """Raised when we couldn't find a free code after MAX_ATTEMPTS tries."""


def generate_nominee_code(category):
    """Generate a unique code for a new nominee in the given category.

    The code is the category's letter plus a random two-digit number
    (10-99), e.g. "B47". It's random rather than sequential (B10, B11, B12,
    ...) on purpose: a sequential code would let anyone guess how many
    nominees exist in a category, or guess a nominee's code just by trying
    numbers in order.

    We pick a random number and check it isn't already used in this
    category; if it is, we just try again. Giving up after MAX_ATTEMPTS
    tries avoids looping forever if a category somehow runs out of room
    (there are only 90 possible numbers per letter).

    This check-then-use approach has a small race-condition window if two
    requests check at the same time (see the retry logic around
    db.session.commit() in the approve route) -- the real guard against a
    duplicate code is the (category_id, code) unique constraint on the
    Nominee table itself, which this function relies on the database to
    enforce.
    """
    for _ in range(MAX_ATTEMPTS):
        number = random.randint(10, 99)
        code = f"{category.code_letter}{number}"

        already_used = Nominee.query.filter_by(category_id=category.id, code=code).first()
        if already_used is None:
            return code

    raise CodeGenerationError(
        f"could not generate a unique code for category '{category.code_letter}' "
        f"after {MAX_ATTEMPTS} attempts"
    )
