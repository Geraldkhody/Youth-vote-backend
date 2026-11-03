import pytest

from app.extensions import db
from app.models.category import Category
from app.models.nominee import Nominee
from app.services.codes import CodeGenerationError, generate_nominee_code


def test_generate_nominee_code_format(app):
    with app.app_context():
        category = Category(name="Test", code_letter="Z", is_active=True)
        db.session.add(category)
        db.session.commit()

        code = generate_nominee_code(category)

        assert code[0] == "Z"
        assert 10 <= int(code[1:]) <= 99


def test_generate_nominee_code_gives_up_after_200_tries(app):
    with app.app_context():
        category = Category(name="Full Category", code_letter="X", is_active=True)
        db.session.add(category)
        db.session.commit()

        # Fill every possible code (X10 through X99) so there's nothing left to pick.
        for number in range(10, 100):
            db.session.add(Nominee(
                category_id=category.id,
                code=f"X{number}",
                full_name="Someone",
                phone="233241234567",
            ))
        db.session.commit()

        with pytest.raises(CodeGenerationError):
            generate_nominee_code(category)
