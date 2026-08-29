from uuid import uuid4

import pytest

from app.modules.ai_training.application.review_service import (
    ReviewError,
    ReviewService,
    is_non_product_class,
)


def test_dining_table_is_non_product():
    assert is_non_product_class("dining table") is True
    assert is_non_product_class("Dining Table") is True
    assert is_non_product_class("bottle") is False
    assert is_non_product_class("du_7u") is False
    assert is_non_product_class("MG-HH") is False
    assert is_non_product_class(None) is False


@pytest.mark.asyncio
async def test_record_human_sku_correction_requires_crop():
    svc = ReviewService(session=None, storage=None)  # type: ignore[arg-type]
    with pytest.raises(ReviewError, match="crop"):
        await svc.record_human_sku_correction(
            organization_id=uuid4(),
            crop_key="  ",
            confirmed_product_id=uuid4(),
            reviewed_by=None,
        )
