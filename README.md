# Bulk Action Platform for CRM Applications

> **Candidate:** Fenil Domadiya  
> **Role:** Senior Backend Engineer Submission  
> **Company / Reviewer:** Shipmnts (Saumya Shah)  
> **Tech Stack:** Python 3.12+, Django 6, Django REST Framework (DRF), Celery, Redis 7, PostgreSQL 17, Docker Compose

---

## Executive Summary & Deliverables

The **Bulk Action Platform** is an enterprise-grade, horizontally scalable distributed system designed to execute asynchronous, high-volume batch operations across CRM entities (such as Contacts, Leads, Companies, Deals, and Tasks) with high throughput, strict idempotency, and robust error recovery.

### Submission Deliverables Checklist
- [x] **GitHub Repository**: Complete source code with git history, layered architecture, and unit tests.
- [x] **Postman Collection**: [`Bulk_Action_Platform.postman_collection.json`](Bulk_Action_Platform.postman_collection.json) (v2.1.0 format with environment variables and assertions).
- [x] **Loom Video Script & Talking Points**: [`docs/loom_presentation_guide.md`](docs/loom_presentation_guide.md) (structured 5-to-7 minute walkthrough guide).
- [x] **Pre-seeded Database Dump**: [`dump.sql`](dump.sql) (PostgreSQL 17 dump containing schema, admin user, and sample contacts).
- [x] **Containerized Infrastructure**: [`docker-compose.yml`](docker-compose.yml) (PostgreSQL 17 and Redis 7).
- [x] **One-Click Automation**: [`Makefile`](Makefile) (`make docker-up`, `make db-restore`, `make server`, `make worker`, `make beat`, `make test`).
- [x] **Interactive OpenAPI 3.0 Documentation**:
  - Swagger UI: [**`http://localhost:8000/api/docs/`**](http://localhost:8000/api/docs/)
  - Redoc: [**`http://localhost:8000/api/redoc/`**](http://localhost:8000/api/redoc/)
  - OpenAPI Spec File: [`Bulk Action Platform API.yaml`](Bulk%20Action%20Platform%20API.yaml)
- [x] **Comprehensive Documentation**: Located in [`/docs`](docs/) directory.

---

## Architecture & System Design

The platform strictly adheres to a **layered architecture** as defined in `GEMINI.md`:

```
HTTP Request (Client / Admin UI / Integrations)
      │
      ▼
 View / ViewSet         (Thin: validates serializer, checks permissions, delegates to service)
      │
      ▼
 Service Layer          (Business logic, rate-limit enforcement, chunk partitioning, Celery dispatch)
      │
      ▼
 Repository Layer       (Exclusive owner of ORM queries, bulk_update, bulk_create, atomic increments)
      │
      ▼
 Models & Database      (PostgreSQL 17 relational persistence, constraints, indexes)
```

### High-Level System Architecture

```
                                ┌───────────────────────────┐
                                │      Client / API         │
                                └─────────────┬─────────────┘
                                              │ POST /api/bulk-actions/
                                              ▼
                                ┌───────────────────────────┐
                                │    BulkActionService      │
                                └──────┬─────────────┬──────┘
                   1. Rate Limit Check │             │ 2. Chunk Workload (500/chunk)
                                       ▼             ▼
                        ┌──────────────────┐   ┌──────────────────────────┐
                        │ Redis Limiter    │   │ BulkAction & Chunk Models│
                        │ (Sliding Window) │   └─────────────┬────────────┘
                        └──────────────────┘                 │ 3. Dispatch Tasks
                                                             ▼
                                                    ┌─────────────────┐
                                                    │  Celery Broker  │
                                                    │     (Redis)     │
                                                    └────────┬────────┘
                                                             │
                                ┌────────────────────────────┼────────────────────────────┐
                                │                            │                            │
                                ▼                            ▼                            ▼
                        ┌──────────────┐             ┌──────────────┐             ┌──────────────┐
                        │ Worker Pod 1 │             │ Worker Pod 2 │             │ Worker Pod N │
                        │ (Chunk #1)   │             │ (Chunk #2)   │             │ (Chunk #N)   │
                        └──────┬───────┘             └──────┬───────┘             └──────┬───────┘
                               │                            │                            │
                               └────────────────────────────┼────────────────────────────┘
                                                            ▼
                                              ┌───────────────────────────┐
                                              │   ChunkExecutionService   │
                                              ├───────────────────────────┤
                                              │ • Row Lock (idempotency)  │
                                              │ • Redis Email Dedup       │
                                              │ • Bulk Fetch (id__in)     │
                                              │ • ActionStrategy.execute  │
                                              │ • bulk_update() Entities  │
                                              │ • bulk_create() Logs      │
                                              │ • Atomic F() Increments   │
                                              └─────────────┬─────────────┘
                                                            ▼
                                              ┌───────────────────────────┐
                                              │       PostgreSQL 17       │
                                              └───────────────────────────┘
```

---

## Core Features & Implementation Highlights

### 1. Modular Strategy Pattern
- **Abstract Base Class (`ActionStrategy`)**: Enforces a standard contract with `validate_payload(model_class, payload)` and `execute(entities, payload, action)`.
- **`BulkUpdateStrategy`**: Dynamically inspects Django model metadata (`model_class._meta.get_field(name)`) to validate and update arbitrary fields on any entity without hardcoded field mappings.
- **`StrategyFactory`**: Extensible registry mapping action types (e.g. `bulk_update`, `bulk_delete`, `bulk_assign`) to strategy implementations.

### 2. Entity-Agnostic Design (`EntityRegistry`)
The system is decoupled from concrete models. Adding any new CRM entity (e.g., `Lead`, `Company`, `Deal`, `Task`) takes **only two steps**:
```python
# 1. Define model repository
class LeadRepository(BaseEntityRepository[Lead]):
    def get_model_class(self):
        return Lead

# 2. Register with registry
EntityRegistry.register("lead", LeadRepository(), email_field="email")
```
Once registered, `POST /api/bulk-actions/` immediately supports `"entity_type": "lead"` with zero changes to views, serializers, or worker tasks.

### 3. Horizontal Scaling & Workload Chunking
- When a bulk action is submitted (e.g. 10,000 entities), the service divides the IDs into chunks of **500 records each** (configurable via `chunk_size`).
- Each chunk is recorded in `BulkActionChunk` with `start_index` and `end_index` and dispatched as an independent Celery task (`process_bulk_action_chunk.delay(chunk.id)`).
- Multiple Celery workers across pods or machines process chunks concurrently in parallel.

### 4. Database Efficiency (Zero N+1 Queries)
- **Batch Entity Retrieval**: Workers fetch chunk records in a single query:
  `repository.get_by_ids(chunk.entity_ids)` (`SELECT ... WHERE id IN (...)`).
- **Batch Entity Updates**: Modified records are committed via Django's `bulk_update(entities, fields=...)` in a single SQL operation.
- **Batch Audit Logging**: Per-record results (`BulkActionLog`) are committed via `bulk_create(logs, batch_size=500)`.
- **Atomic Counter Increments (`F()` Expressions)**: Progress counters are incremented atomically at the database level, avoiding worker race conditions and lock contention:
  ```python
  BulkAction.objects.filter(id=action_id).update(
      success_count=F("success_count") + result.success_count,
      failure_count=F("failure_count") + result.failure_count,
      skipped_count=F("skipped_count") + result.skipped_count,
  )
  ```

### 5. Multi-Tenant Rate Limiting (Redis Sliding Window)
- **Requirement**: Restrict each tenant (`account_id`) to a maximum of **10,000 entities per minute**.
- **Implementation**: Implemented using an atomic Redis Lua script over a 60-second sliding window (`rate_limit:{account_id}`).
- Limits are evaluated and consumed **before tasks are queued**. If a request exceeds the quota, it is rejected immediately with **`429 Too Many Requests`**, preserving worker queues.

### 6. Distributed In-Action Deduplication
- **Requirement**: Within a single bulk action, duplicate records sharing the same `email` must be skipped and logged as `SKIPPED`.
- **Implementation**: Evaluated across concurrent workers using Redis Sets (`bulk_action:{id}:seen_emails`). The atomic `SADD` operation ensures that exactly the first instance processes while duplicates are safely flagged as `SKIPPED` with an audit message.

### 7. Future Scheduling (Celery Beat)
- **Requirement**: Support future scheduling (e.g. run on Nov 22 at 11:15 PM).
- **Implementation**: Actions with a future `scheduled_at` timestamp are persisted in `SCHEDULED` status without queuing immediate worker tasks.
- A periodic Celery Beat task (`process_scheduled_actions`) runs every 30 seconds to locate due actions, verify tenant rate limits, and transition them to `RUNNING` by dispatching chunk tasks.

### 8. Reliability: Celery Late Acknowledgment & Idempotency
- **Celery Late Ack**: Configured with `task_acks_late = True` and `task_reject_on_worker_lost = True`. If a worker crashes or encounters an OOM killer mid-chunk, the task is automatically returned to the broker rather than lost.
- **Idempotent Chunk Processing**:
  - Each worker acquires a row-level lock on the chunk (`select_for_update()`).
  - If `chunk.status == COMPLETED`, the worker exits immediately (safe no-op).
  - The entire chunk execution runs inside `@transaction.atomic`, ensuring partial failures never leave corrupted counters or orphan logs.

---

## Quick Start Guide

### Option 1: Fast Start with Docker & Database Dump (Recommended)

1. **Clone the repository and enter the directory**:
   ```bash
   git clone <repo-url>
   cd bulk_action_platform
   ```

2. **Start PostgreSQL 17 and Redis 7 containers**:
   ```bash
   make docker-up
   # Or: docker compose up -d
   ```

3. **Set up virtual environment & install dependencies**:
   ```bash
   make venv
   make install
   ```

4. **Restore the pre-seeded database dump**:
   ```bash
   make db-restore
   ```
   *Note: `dump.sql` includes the database schema, default admin user (`admin` / `admin123`), and 1,000 sample contacts.*

5. **Start services (in separate terminal tabs)**:
   ```bash
   # Terminal 1: Django API Server & Admin
   make server

   # Terminal 2: Celery Worker
   make worker

   # Terminal 3: Celery Beat Scheduler
   make beat
   ```

---

### Option 2: Clean Setup from Scratch

```bash
# 1. Start containers
make docker-up

# 2. Virtual environment and dependencies
make venv && make install

# 3. Apply migrations
make migrate

# 4. Create default superuser (admin / admin123)
make superuser

# 5. Seed sample contacts (1,000 contacts for testing, or use make seed-large for 10,000)
make seed

# 6. Start services
make server  # Port 8000
make worker  # 4 concurrency
make beat    # Periodic scheduler
```

---

## Makefile Command Cheatsheet

| Command | Description |
|---|---|
| `make docker-up` | Start PostgreSQL 17 and Redis 7 containers via Docker Compose |
| `make docker-down` | Stop and remove Docker containers |
| `make db-dump` | Export current database to `dump.sql` |
| `make db-restore` | Restore database state from `dump.sql` |
| `make server` | Start Django development server on `0.0.0.0:8000` |
| `make worker` | Start Celery worker with 4 concurrent processes |
| `make beat` | Start Celery Beat periodic scheduler |
| `make worker-beat` | Run Celery worker and beat together in a single process |
| `make migrate` | Run Django database migrations |
| `make superuser` | Create default admin superuser (`admin` / `admin123`) |
| `make seed` | Seed 1,000 sample contacts for testing |
| `make seed-large` | Seed 10,000 sample contacts for load testing |
| `make test` | Run automated test suite with pytest |
| `make lint` | Run Ruff linter checks |
| `make format` | Automatically format code with Ruff |

---

## API Reference & Usage Examples

### Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/bulk-actions/` | Create a bulk action (immediate or scheduled). Partitions into chunks and queues tasks. |
| `GET` | `/api/bulk-actions/` | List bulk actions with filtering (`account_id`, `status`, `entity_type`). |
| `GET` | `/api/bulk-actions/{id}/` | Get action details and real-time completion progress. |
| `GET` | `/api/bulk-actions/{id}/stats/` | Get statistical summary and chunk-level execution breakdown. |
| `GET` | `/api/bulk-actions/{id}/logs/` | Get paginated entity execution logs with status filter (`SUCCESS`, `ERROR`, `SKIPPED`). |
| `GET` | `/api/docs/` | Interactive Swagger UI (OpenAPI 3.0). |
| `GET` | `/api/redoc/` | Interactive Redoc API documentation. |

---

### 1. Create a Bulk Action
**`POST /api/bulk-actions/`**

```bash
curl -X POST http://localhost:8000/api/bulk-actions/ \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "tenant_123",
    "entity_type": "contact",
    "action_type": "bulk_update",
    "payload": {
      "entity_ids": [1, 2, 3, 4, 5],
      "fields": {
        "status": "archived",
        "age": 35
      }
    },
    "chunk_size": 500
  }'
```

**Response (`201 Created`):**
```json
{
  "id": "e305e608-d306-4b89-a2e6-a052ff6b7e52",
  "account_id": "tenant_123",
  "entity_type": "contact",
  "action_type": "bulk_update",
  "payload": {
    "entity_ids": [1, 2, 3, 4, 5],
    "fields": { "status": "archived", "age": 35 }
  },
  "status": "RUNNING",
  "total_count": 5,
  "success_count": 0,
  "failure_count": 0,
  "skipped_count": 0,
  "progress_percentage": 0.0,
  "scheduled_at": null,
  "created_at": "2026-10-09T01:50:00.123456Z",
  "updated_at": "2026-10-09T01:50:00.123456Z"
}
```

*When rate limit is exceeded (`429 Too Many Requests`):*
```json
{
  "error": "Rate limit exceeded. Maximum 10000 entities per minute.",
  "account_id": "tenant_123",
  "limit_per_minute": 10000,
  "current_usage": 9800,
  "requested": 500
}
```

---

### 2. Schedule Action for Future Execution
**`POST /api/bulk-actions/`**

```bash
curl -X POST http://localhost:8000/api/bulk-actions/ \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "tenant_enterprise",
    "entity_type": "contact",
    "action_type": "bulk_update",
    "payload": {
      "entity_ids": [10, 11, 12],
      "fields": { "status": "active" }
    },
    "chunk_size": 500,
    "scheduled_at": "2026-11-22T23:15:00Z"
  }'
```
*The action is saved in `SCHEDULED` status and Celery Beat automatically initiates execution when the timestamp arrives.*

---

### 3. Get Action Status & Progress
**`GET /api/bulk-actions/{id}/`**

```bash
curl http://localhost:8000/api/bulk-actions/e305e608-d306-4b89-a2e6-a052ff6b7e52/
```

**Response (`200 OK`):**
```json
{
  "id": "e305e608-d306-4b89-a2e6-a052ff6b7e52",
  "account_id": "tenant_123",
  "entity_type": "contact",
  "action_type": "bulk_update",
  "status": "COMPLETED",
  "total_count": 1000,
  "success_count": 980,
  "failure_count": 10,
  "skipped_count": 10,
  "progress_percentage": 100.0,
  "created_at": "2026-10-09T01:50:00Z",
  "updated_at": "2026-10-09T01:50:12Z"
}
```

---

### 4. Get Statistics Breakdown
**`GET /api/bulk-actions/{id}/stats/`**

```bash
curl http://localhost:8000/api/bulk-actions/e305e608-d306-4b89-a2e6-a052ff6b7e52/stats/
```

**Response (`200 OK`):**
```json
{
  "id": "e305e608-d306-4b89-a2e6-a052ff6b7e52",
  "account_id": "tenant_123",
  "status": "COMPLETED",
  "total_count": 1000,
  "success_count": 980,
  "failure_count": 10,
  "skipped_count": 10,
  "progress_percentage": 100.0,
  "chunks": {
    "total": 2,
    "completed": 2,
    "failed": 0,
    "running": 0,
    "pending": 0
  }
}
```

---

### 5. Get Paginated Execution Logs (Filtered by Status)
**`GET /api/bulk-actions/{id}/logs/?status=SKIPPED`**

```bash
curl "http://localhost:8000/api/bulk-actions/e305e608-d306-4b89-a2e6-a052ff6b7e52/logs/?status=SKIPPED&page=1&page_size=10"
```

**Response (`200 OK`):**
```json
{
  "count": 10,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 42,
      "bulk_action_id": "e305e608-d306-4b89-a2e6-a052ff6b7e52",
      "entity_id": "105",
      "status": "SKIPPED",
      "error_message": "Duplicate entity with email 'alex@example.com' skipped.",
      "created_at": "2026-10-09T01:50:05.123456Z"
    }
  ]
}
```

---

## Django Admin Interface

The platform provides a rich Django Admin interface accessible at [**`http://localhost:8000/admin/`**](http://localhost:8000/admin/) (`admin` / `admin123`):

1. **`BulkActionAdmin`**:
   - Visual progress badges and completion percentage bars.
   - Tabular inline displaying all associated `BulkActionChunk` records with live status.
   - Batch admin actions: "Process pending chunks now" and "Cancel selected actions".
2. **`BulkActionLogAdmin`**:
   - Color-coded badges for `SUCCESS` (green), `SKIPPED` (amber), and `ERROR` (red).
   - Filter logs by status, bulk action, or search by entity ID and error message.
3. **`ContactAdmin` & `LeadAdmin`**:
   - Direct record inspection with search and filtering.
   - Built-in admin list action: "Apply bulk status update", enabling admins to trigger actions directly from the UI.

---

## Architectural Trade-Offs & Engineering Decisions

| Dimension | Decision Taken | Rationale & Trade-off Considered |
|---|---|---|
| **Rate Limiting Algorithm** | **Redis Sliding Window (Lua script)** | **Why:** Enforces a hard, accurate limit of 10,000 entities per 60-second window across distributed workers.<br>**Alternative considered:** Token bucket allows bursts above the limit, which could overwhelm downstream database connections. |
| **Deduplication Scope** | **In-Action Scope via Redis Sets** | **Why:** The brief requests skipping duplicate emails *within a single bulk action*. Using ephemeral Redis keys (`bulk_action:{id}:seen_emails`) with TTL ensures fast atomic `SADD` checks across concurrent workers without polluting permanent storage. |
| **Chunk Size (500 records)** | **Configurable default of 500 records** | **Why:** 500 records balances PostgreSQL query payload size (~500 IDs in `id__in`), memory footprint per Celery worker, and high parallelism without saturating the connection pool. |
| **Celery Acknowledgment** | **Late Ack (`acks_late=True`)** | **Why:** Default early ack causes message loss if a worker crashes or is OOM-killed mid-chunk. With late ack and idempotent chunks, tasks are redelivered cleanly. |
| **Progress Counters** | **Database `F()` expressions** | **Why:** Celery workers run concurrently. Incrementing counters via python object attributes would cause lost updates due to race conditions. Django `F()` offloads atomic increments to PostgreSQL. |
| **Layered Separation** | **Strict Views $\to$ Services $\to$ Repositories** | **Why:** Zero ORM queries in views or serializers. Business logic lives entirely in services. Makes testing isolated, deterministic, and modular. |

---

## Testing & Quality Verification

The test suite covers unit and integration scenarios across all platform layers:

```bash
# Run the test suite
pytest
```

```
tests/test_api.py::TestBulkActionAPI::test_post_bulk_action_creates_action_and_chunks PASSED
tests/test_api.py::TestBulkActionAPI::test_post_bulk_action_rate_limit_exceeded_returns_429 PASSED
tests/test_api.py::TestBulkActionAPI::test_get_bulk_actions_list_and_filters PASSED
tests/test_api.py::TestBulkActionAPI::test_get_bulk_action_detail_and_progress PASSED
tests/test_api.py::TestBulkActionAPI::test_get_bulk_action_stats PASSED
tests/test_api.py::TestBulkActionAPI::test_get_bulk_action_logs_paginated_and_filtered PASSED
tests/test_api.py::TestBulkActionAPI::test_swagger_and_openapi_endpoints PASSED
tests/test_chunking.py::TestHorizontalScalingChunking::test_chunking_splits_workload_into_chunks PASSED
tests/test_chunking.py::TestHorizontalScalingChunking::test_chunk_execution_and_atomic_increments PASSED
tests/test_deduplication.py::TestDeduplication::test_deduplication_skips_duplicate_emails_and_logs_skipped PASSED
tests/test_deduplication.py::TestDeduplication::test_deduplication_scope_is_per_bulk_action PASSED
tests/test_idempotency.py::TestIdempotency::test_rerunning_completed_chunk_does_not_duplicate_results PASSED
tests/test_idempotency.py::TestIdempotency::test_rerunning_failed_chunk_does_not_double_count_when_retried PASSED
tests/test_rate_limiter.py::TestRedisRateLimiter::test_consume_within_limit_success PASSED
tests/test_rate_limiter.py::TestRedisRateLimiter::test_exceeding_limit_is_rejected PASSED
tests/test_rate_limiter.py::TestRedisRateLimiter::test_multi_tenant_isolation PASSED
tests/test_scheduling.py::TestScheduling::test_future_scheduled_action_is_not_dispatched_immediately PASSED
tests/test_scheduling.py::TestScheduling::test_celery_beat_task_triggers_due_actions PASSED
tests/test_strategies.py::TestModularStrategyPattern::test_factory_resolves_bulk_update_strategy PASSED
tests/test_strategies.py::TestModularStrategyPattern::test_validate_payload_rejects_missing_fields PASSED
tests/test_strategies.py::TestModularStrategyPattern::test_validate_payload_rejects_invalid_model_fields PASSED
tests/test_strategies.py::TestModularStrategyPattern::test_bulk_update_contact_updates_any_field PASSED
tests/test_strategies.py::TestModularStrategyPattern::test_bulk_update_entity_agnostic_lead PASSED

============================== 23 passed in 1.86s ==============================
```

Linting and code style verification:
```bash
ruff check .
# All checks passed!
```

---

## Detailed Documentation Directory

For deep-dive guides, refer to the [`docs/`](docs/) directory:
- [**Documentation Index**](docs/index.md): Complete navigation guide.
- [**System Architecture & Diagrams**](docs/architecture.md): Layered architecture, Mermaid sequence and ER diagrams.
- [**Modular Strategy Pattern**](docs/strategy_pattern.md): Entity agnosticism and step-by-step tutorial on adding new actions.
- [**Concurrency & Performance Guide**](docs/concurrency_and_performance.md): Chunking, rate limiting, deduplication, and late ack analysis.
- [**Creating & Monitoring Bulk Actions**](docs/creating_bulk_actions.md): Step-by-step user guide for API and Django Admin.
- [**Setup & Operations Guide**](docs/setup_guide.md): Environment variables, Docker, Celery, and operations.
- [**Loom Video Presentation Guide**](docs/loom_presentation_guide.md): 5-to-7 minute presentation script for Saumya Shah and the Shipmnts review team.
