# VisionMart

> Enterprise AI Smart Retail Platform powered by Computer Vision.

**Domain:** [visionmart.thehuan.com](https://visionmart.thehuan.com/)
**Version:** `0.1.0` — Sprint 01 (Foundation)
**License:** See [LICENSE](LICENSE)

---

## 1. Project Overview

VisionMart is a production-grade Smart Retail AI platform that combines real-time computer vision, distributed services, and a unified operator dashboard to transform brick-and-mortar retail.

Sprint 01 delivers the **architectural foundation** only — no business features, APIs, authentication, database tables, AI models, or frontend pages are implemented yet.

## 2. Vision

Become the leading enterprise Smart Retail AI Platform across multi-camera, multi-branch retail operations, with capabilities including:

- AI Product Detection & Customer Tracking
- Smart Cart, Inventory AI, Queue & Theft Detection
- Heatmap, Customer Analytics, Staff Analytics
- Notification Center, REST API, WebSocket, MQTT
- Multi-branch operations and future mobile companion app

## 3. Architecture

VisionMart applies **Clean Architecture**, **Domain Driven Design (DDD)**, and a **Modular Monolith** pattern for the MVP — designed so the AI Engine can later be **extracted into a standalone service without changing the public API**.

```
                       ┌──────────────────────────┐
                       │   Nginx (Reverse Proxy)  │
                       └────┬───────────────┬─────┘
                            │               │
                  ┌─────────▼──┐       ┌────▼─────────┐
                  │  Frontend  │       │   Backend    │
                  │ React/Vite │       │   FastAPI    │
                  └────────────┘       └──┬────────┬──┘
                                          │        │
                                ┌─────────▼─┐  ┌───▼────────┐
                                │ AI Engine │  │  Celery    │
                                │  FastAPI  │  │  Workers   │
                                └─────────┬─┘  └───┬────────┘
                                          │        │
                ┌─────────────────────────┴────────┴─────────┐
                │                                            │
        ┌───────▼─────┐  ┌──────────────┐  ┌──────────────┐  │
        │ PostgreSQL  │  │    Redis     │  │    MinIO     │  │
        └─────────────┘  └──────────────┘  └──────────────┘  │
                                                             │
                          Future: MQTT Broker / Edge Nodes ──┘
```

Principles applied:

- Clean Architecture (api → service → repository → model)
- SOLID + Repository + Service Layer + Dependency Injection
- Event-Driven ready (internal event bus interface, future broker)
- Async-first I/O (`asyncpg`, `httpx`, `asyncio`)

## 4. Technology Stack

| Layer        | Stack                                                        |
| ------------ | ------------------------------------------------------------ |
| Backend      | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2   |
| Async        | Celery, Redis                                                |
| Database     | PostgreSQL 16                                                |
| Object Store | MinIO (S3-compatible)                                        |
| Frontend     | React 18, TypeScript, Vite, Tailwind CSS, Ant Design         |
| Data Layer   | React Query, React Router                                    |
| AI Engine    | Python, OpenCV, Ultralytics YOLOv8, ByteTrack, ONNX Runtime  |
| Infra        | Docker, Docker Compose, Nginx, Ubuntu 24.04 LTS              |
| CI/CD        | GitHub Actions                                               |

## 5. Folder Structure

```
VisionMart/
├── backend/            # FastAPI modular monolith (Clean Architecture)
├── frontend/           # React + Vite + TypeScript SPA
├── ai-engine/          # Computer Vision service (separable)
├── docker/             # Dockerfiles & service configs (nginx, postgres)
├── deployment/         # Production deployment assets
├── docs/               # Architecture and design documentation
├── scripts/            # Developer utility scripts
├── datasets/           # (gitignored) Local datasets
├── models/             # (gitignored) Trained model weights
├── storage/            # (gitignored) Local object storage mount
├── tests/              # Cross-module integration tests
├── .github/workflows/  # CI/CD pipelines
├── docker-compose.yml
├── Makefile
├── .editorconfig
├── .pre-commit-config.yaml
├── .env.example
└── README.md
```

See `backend/`, `frontend/`, and `ai-engine/` for per-service layouts.

## 6. Local Development

### Prerequisites

- Docker + Docker Compose v2
- Git
- Node.js 20+ (optional, for native frontend dev)
- Python 3.12+ (optional, for native backend dev)
- `make` (Windows: via Git Bash, WSL, or Chocolatey)

### First-time setup

```bash
git clone https://github.com/huanbv/VisionMart.git
cd VisionMart
cp .env.example .env
make setup
```

### Run the full stack

```bash
make up          # docker compose up -d
make logs        # tail logs
make down        # stop everything
```

### Service URLs (local)

| Service       | URL                                |
| ------------- | ---------------------------------- |
| Frontend      | http://localhost:3000              |
| Backend API   | http://localhost:8000/docs         |
| AI Engine     | http://localhost:8100/health       |
| MinIO Console | http://localhost:9001              |
| PostgreSQL    | localhost:5432                     |
| Redis         | localhost:6379                     |

## 7. Docker Commands

| Command               | Description                          |
| --------------------- | ------------------------------------ |
| `make build`          | Build all images                     |
| `make up`             | Start all services in background     |
| `make down`           | Stop and remove all services         |
| `make restart`        | Restart all services                 |
| `make logs`           | Tail logs for all services           |
| `make ps`             | List running services                |
| `make backend-shell`  | Open shell in backend container      |
| `make frontend-shell` | Open shell in frontend container     |
| `make ai-shell`       | Open shell in ai-engine container    |
| `make lint`           | Run linters across the monorepo      |
| `make format`         | Auto-format the monorepo             |
| `make test`           | Run all tests                        |

## 8. Versioning Strategy

VisionMart follows [Semantic Versioning 2.0.0](https://semver.org/).

- **MAJOR** — breaking public API/contract changes.
- **MINOR** — backward-compatible features.
- **PATCH** — backward-compatible fixes.
- **Pre-release** — `-alpha.N`, `-beta.N`, `-rc.N`.

Git workflow: **trunk-based** with short-lived feature branches → PR → squash merge into `main`. Releases are cut from `main` with annotated tags (`v0.1.0`).

## 9. Roadmap

| Sprint | Theme                                |
| ------ | ------------------------------------ |
| 01     | Foundation: architecture, infra, DX  |
| 02     | Core domain, auth, RBAC, DB schema   |
| 03     | Camera Manager, Video Pipeline       |
| 04     | Object Detection + Tracking          |
| 05     | Product Recognition + Cart Engine    |
| 06     | Real-time Dashboard + WebSocket      |
| 07     | Analytics: Heatmap, Customer, Staff  |
| 08     | Inventory AI + Queue/Theft Detection |
| 09     | Multi-branch + Notifications + MQTT  |
| 10     | Hardening, CI/CD, GPU deployment     |

## 10. License

This project is distributed under the terms described in [LICENSE](LICENSE).

---

_For detailed design documents see [docs/](docs/)._
