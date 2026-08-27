from app.modules.ai_training.application.review_service import is_non_product_class


def test_dining_table_is_non_product():
    assert is_non_product_class("dining table") is True
    assert is_non_product_class("Dining Table") is True
    assert is_non_product_class("bottle") is False
    assert is_non_product_class("du_7u") is False
    assert is_non_product_class(None) is False
