# Design

Phase 0 establishes the service foundation only. The codebase uses a layered
FastAPI application, SQLAlchemy 2.0 for persistence, Alembic for schema changes,
PostgreSQL as the relational database, and Redis as the cache/key-value service.

Planned package boundaries:

- `app/api/`: HTTP routing and dependency wiring.
- `app/schemas/`: request and response validation models.
- `app/services/`: application use cases and business rules.
- `app/models/`: SQLAlchemy persistence models.
- `app/core/`: settings and shared infrastructure.

No routes, domain models, or API key behavior are implemented in this phase.
