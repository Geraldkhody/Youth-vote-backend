from flask import Blueprint, jsonify, request

from app.auth_utils import admin_required
from app.models.category import Category
from app.services.categories import create_category, update_category

# url_prefix means every route below is actually "/api/categories..."
categories_bp = Blueprint("categories", __name__, url_prefix="/api/categories")

# A second blueprint for the admin-only "/api/admin/categories" listing,
# since it lives under a different URL prefix than the rest of this file.
admin_categories_bp = Blueprint("admin_categories", __name__, url_prefix="/api/admin/categories")


@categories_bp.post("")
@admin_required
def create_category_route():
    data = request.get_json(silent=True) or {}

    try:
        category = create_category(
            name=data.get("name"),
            code_letter=data.get("code_letter"),
            description=data.get("description"),
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return jsonify(category.to_dict()), 201


@categories_bp.get("")
def list_categories():
    """Public: active categories only."""
    categories = (
        Category.query.filter_by(is_active=True).order_by(Category.code_letter).all()
    )
    return jsonify([category.to_dict() for category in categories])


@categories_bp.get("/<int:category_id>")
def get_category(category_id):
    category = Category.query.get(category_id)
    if category is None:
        return jsonify(error="category not found"), 404

    return jsonify(category.to_dict())


@categories_bp.patch("/<int:category_id>")
@admin_required
def update_category_route(category_id):
    category = Category.query.get(category_id)
    if category is None:
        return jsonify(error="category not found"), 404

    data = request.get_json(silent=True) or {}

    try:
        category = update_category(
            category,
            name=data.get("name"),
            description=data.get("description"),
            is_active=data.get("is_active"),
            code_letter=data.get("code_letter"),
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return jsonify(category.to_dict())


@admin_categories_bp.get("")
@admin_required
def list_all_categories():
    """Admin: every category, including inactive ones."""
    categories = Category.query.order_by(Category.code_letter).all()
    return jsonify([category.to_dict() for category in categories])
