# VisionMart

> AI-powered Smart Retail Platform using Computer Vision.

**Domain:** [visionmart.thehuan.com](https://visionmart.thehuan.com/)
**Version:** 0.1.0 (Scaffold)
**License:** See [LICENSE](LICENSE)

---

## 1. Project Description

VisionMart is an enterprise-grade **Smart Retail AI Platform** that leverages Computer Vision and real-time analytics to transform physical retail operations.

The platform is designed to:

- Detect customers entering and moving through the store.
- Recognize products on shelves and in customer hands.
- Track shopping activities and virtual cart interactions.
- Analyze customer behavior (dwell time, heatmaps, traffic flow).
- Manage inventory levels in real time.
- Provide store managers with a live, data-driven dashboard.

The MVP is built as a modular foundation that will evolve into a full **Enterprise Smart Retail AI Platform** supporting multi-store deployments, edge inference, and SaaS-grade tenancy.

---

## 2. Architecture Overview

VisionMart follows **Clean Architecture**, **SOLID principles**, and **Domain Driven Design**, with a clear separation between business logic and infrastructure.

High-level components:

| Layer            | Responsibility                                                       |
| ---------------- | -------------------------------------------------------------------- |
| **Frontend**     | Operator dashboard, analytics UI, real-time monitoring               |
| **Backend API**  | Business logic, REST + WebSocket APIs, authentication, orchestration |
| **AI Engine**    | Computer Vision pipeline (detection, tracking, recognition)          |
| **Workers**      | Asynchronous jobs (Celery) for analytics and batch processing        |
| **Data Stores**  | PostgreSQL (relational), Redis (cache/queue), MinIO (objects/media)  |
| **Edge / Proxy** | Nginx reverse proxy, TLS termination, routing                        |

Communication patterns:

- **REST** for synchronous client/server operations.
- **WebSocket** for real-time dashboard updates and events.
- **Message Queue (Redis + Celery)** for asynchronous AI/analytics pipelines.
- **Object Storage (MinIO)** for frames, snapshots, exports, and model artifacts.

The entire system is **containerized via Docker** and orchestrated via **Docker Compose**, ready for migration to Kubernetes in future cloud deployments.

---

## 3. Technology Stack

### Backend
- Python 3.12
- FastAPI
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- Redis
- Celery
- JWT Authentication
- WebSocket
- Pydantic V2

### AI
- Python
- OpenCV
- Ultralytics YOLOv8
- ByteTrack
- ONNX Runtime

### Frontend
- React
- TypeScript
- Vite
- TailwindCSS
- Ant Design
- React Query
- React Router

### Infrastructure
- Docker
- Docker Compose
- Nginx
- Ubuntu Server
- GitHub Actions

### Storage
- MinIO

---

## 4. Folder Structure

```
VisionMart/
├── backend/                 # FastAPI service (Clean Architecture)
│   ├── app/
│   │   ├── api/             # API entry points
│   │   ├── core/            # Core domain logic, base classes
│   │   ├── config/          # App configuration
│   │   ├── database/        # DB session, engine, migrations glue
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── schemas/         # Pydantic v2 schemas (DTOs)
│   │   ├── repositories/    # Data access layer
│   │   ├── services/        # Business / use-case layer
│   │   ├── dependencies/    # DI providers
│   │   ├── middleware/      # FastAPI middleware
│   │   ├── routers/         # API routers
│   │   ├── utils/           # Helpers
│   │   └── workers/         # Celery tasks
│   ├── tests/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                # React + Vite + TS dashboard
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   ├── layouts/
│   │   ├── pages/
│   │   ├── routes/
│   │   ├── hooks/
│   │   ├── contexts/
│   │   ├── services/
│   │   ├── api/
│   │   ├── stores/
│   │   ├── types/
│   │   ├── utils/
│   │   └── styles/
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
│
├── ai-engine/               # Computer Vision pipeline
│   ├── detection/           # YOLOv8 detection
│   ├── tracking/            # ByteTrack
│   ├── recognition/         # Product / customer recognition
│   ├── cart/                # Virtual cart logic
│   ├── heatmap/             # Heatmap generation
│   ├── analytics/           # Behavior analytics
│   ├── inventory/           # Shelf / stock vision
│   ├── models/              # Model definitions
│   ├── weights/             # Trained weights (gitignored)
│   ├── datasets/            # Local datasets (gitignored)
│   ├── services/            # AI service interfaces
│   ├── utils/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── docs/                    # Project documentation
│   ├── 00_PROJECT_OVERVIEW.md
│   ├── 01_PRD.md
│   ├── 02_SOFTWARE_ARCHITECTURE.md
│   ├── 03_TECH_STACK.md
│   ├── 04_FOLDER_STRUCTURE.md
│   ├── 05_DEVELOPMENT_ROADMAP.md
│   ├── 06_CODING_STANDARD.md
│   ├── 07_DEPLOYMENT_PLAN.md
│   ├── 08_SECURITY_GUIDELINE.md
│   └── 09_DEV_ENVIRONMENT.md
│
├── docker/                  # Dockerfiles, build assets
├── deployment/              # Nginx, systemd, deploy scripts
├── datasets/                # Shared datasets
├── models/                  # Shared model artifacts
├── storage/                 # Local storage mount (dev)
├── scripts/                 # Maintenance / automation scripts
├── tests/                   # Cross-module integration tests
├── .github/                 # GitHub Actions workflows
│
├── docker-compose.yml
├── README.md
└── LICENSE
```

---

## 5. Development Roadmap

The platform is built incrementally. Each phase produces a verifiable, production-grade increment.

| Phase | Milestone                          | Scope                                                                  |
| ----- | ---------------------------------- | ---------------------------------------------------------------------- |
| 0     | **Project Scaffold**               | Folder structure, empty modules, README, docker-compose placeholders   |
| 1     | **Core Backend Foundation**        | FastAPI app, config, DB, migrations, auth (JWT), base DI               |
| 2     | **Domain Models & Repositories**   | Users, stores, products, cameras, inventory entities                   |
| 3     | **AI Engine Core**                 | YOLOv8 detection + ByteTrack tracking pipeline                         |
| 4     | **Recognition & Cart Logic**       | Product recognition, virtual cart, event publishing                    |
| 5     | **Real-time Dashboard**            | React dashboard, WebSocket live feeds, KPIs                            |
| 6     | **Analytics & Heatmaps**           | Behavior analytics, heatmap generation, reporting                      |
| 7     | **Inventory Intelligence**         | Shelf monitoring, stock-out detection, alerts                          |
| 8     | **DevOps & CI/CD**                 | GitHub Actions, image registry, staging deploy                         |
| 9     | **Production Hardening**           | Security, observability, performance, backup strategy                  |
| 10    | **Enterprise Evolution**           | Multi-tenant, multi-store, edge inference, SaaS billing                |

---

## 6. Version

**Current Version:** `0.1.0` — Initial scaffold (no business logic implemented yet).

Versioning follows [Semantic Versioning 2.0.0](https://semver.org/).

---

## 7. License

This project is distributed under the terms described in the [LICENSE](LICENSE) file. All rights reserved by the project author unless otherwise stated.

---

## 8. Contributing

VisionMart is an enterprise-grade project. Contributions must follow strict quality standards.

### Workflow

1. **Fork & branch** from `main` using the convention:
   - `feature/<short-description>`
   - `fix/<short-description>`
   - `chore/<short-description>`
2. **Write clean code** — follow SOLID, Clean Architecture, and the project's coding standards (see `docs/06_CODING_STANDARD.md`).
3. **Add tests** for any new business logic.
4. **Run linters and tests locally** before opening a PR.
5. **Open a Pull Request** with a clear description, linked issues, and screenshots/recordings if UI-related.
6. **Code Review** — at least one approval is required before merge.

### Commit Convention

Use **Conventional Commits** in English:

```
feat(backend): add JWT authentication service
fix(ai-engine): correct ByteTrack ID switch on occlusion
docs(readme): update roadmap section
chore(docker): bump postgres image version
```

### Code Style

- All code, comments, identifiers, and commit messages must be in **English**.
- No business logic in controllers/routers — delegate to services.
- No direct DB access in services — go through repositories.
- Always use Dependency Injection.
- Always separate domain from infrastructure.

---

_Last updated: scaffold phase — awaiting next implementation instruction._
