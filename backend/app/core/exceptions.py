"""Domain-level exception hierarchy. Infrastructure must never raise these directly."""

from __future__ import annotations


class VisionMartError(Exception):
    """Base class for all VisionMart domain errors."""


class NotFoundError(VisionMartError):
    """Requested resource does not exist."""


class ConflictError(VisionMartError):
    """Operation conflicts with the current state of a resource."""


class ValidationError(VisionMartError):
    """Domain-level validation failure (not a Pydantic schema error)."""


class UnauthorizedError(VisionMartError):
    """Authentication failure."""


class ForbiddenError(VisionMartError):
    """Authorization failure."""
