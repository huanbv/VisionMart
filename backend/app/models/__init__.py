"""Central model registry.

Import every module's ORM models here so SQLAlchemy registers them on `Base`
and Alembic autogenerate sees the complete schema.
"""

from __future__ import annotations

from app.database.base import Base  # noqa: F401  - re-exported
from app.database.entity import (  # noqa: F401
    AssociationBase,
    Entity,
    ImmutableEntity,
)

# Bounded-context model registrations (side-effect imports).
from app.modules.ai_pipeline.infrastructure import models as _ai_pipeline  # noqa: F401
from app.modules.ai_training.infrastructure import models as _ai_training  # noqa: F401
from app.modules.audit.infrastructure import models as _audit  # noqa: F401
from app.modules.camera.infrastructure import models as _camera  # noqa: F401
from app.modules.catalog.infrastructure import models as _catalog  # noqa: F401
from app.modules.customer.infrastructure import models as _customer  # noqa: F401
from app.modules.detection.infrastructure import models as _detection  # noqa: F401
from app.modules.employee.infrastructure import models as _employee  # noqa: F401
from app.modules.identity.infrastructure import models as _identity  # noqa: F401
from app.modules.inventory.infrastructure import models as _inventory  # noqa: F401
from app.modules.notification.infrastructure import models as _notification  # noqa: F401
from app.modules.sales.infrastructure import models as _sales  # noqa: F401
from app.modules.tenancy.infrastructure import models as _tenancy  # noqa: F401

__all__ = ["Base", "Entity", "ImmutableEntity", "AssociationBase"]
