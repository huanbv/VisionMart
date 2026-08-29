# Application Modules (Bounded Contexts)

This directory hosts **bounded contexts** of the VisionMart domain — the unit of
isolation in a modular monolith. Each subdirectory is a self-contained module
that owns its own API, schemas, models, services, and repositories.

## Module skeleton

```
app/modules/<module_name>/
├── api/             # FastAPI routers belonging to this module
├── domain/          # Entities, value objects, domain services (pure Python)
├── application/     # Use-cases / service layer (orchestrates domain + infra)
├── infrastructure/  # Repository implementations, external adapters
├── schemas/         # Pydantic v2 DTOs (input/output)
└── __init__.py
```

## Rules

1. **No cross-module imports of `domain/` or `infrastructure/`.** Modules
   communicate via:
   - public application interfaces exposed in `<module>/__init__.py`, or
   - domain events via the shared `EventBus`.
2. **Shared concepts** (currency, ids, value objects used across modules) live
   in `app/shared/`.
3. **Cross-cutting concerns** (logging, config, security, event bus) live in
   `app/core/`.
4. Each module must be **extractable**: moving it into its own service should
   not require touching the public API contract.

## Status

Sprint 01: no modules implemented yet. Bounded contexts will be introduced in
Sprint 02+ (e.g. `auth`, `tenancy`, `camera`, `inventory`, `cart`, `analytics`).
