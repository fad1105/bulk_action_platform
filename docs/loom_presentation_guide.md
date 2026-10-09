# Loom Video Presentation Guide & Talking Points

This guide provides a structured, high-impact outline for recording the **5-to-7 minute Loom video submission** for the Shipmnts technical assignment.

---

## Presentation Blueprint (Target Duration: ~5-7 Minutes)

```
00:00 - 00:45 │ 1. Introduction & Executive Summary
00:45 - 02:00 │ 2. System Architecture & Modularity (Strategy Pattern + Entity Agnosticism)
02:00 - 03:30 │ 3. Scalability, Concurrency & Database Efficiency (Zero N+1, Celery Late Ack)
03:30 - 05:00 │ 4. Live Demo (REST API, Celery Workers, Admin UI, Rate Limiter & Dedup)
05:00 - 06:15 │ 5. Scheduling, Resilience & Edge Cases (Idempotency, Beat)
06:15 - 07:00 │ 6. Assumptions, Trade-offs & Wrap-up
```

---

## 1. Introduction & Executive Summary (0:00 - 0:45)
- **Speaker**: Fenil Domadiya
- **Role**: Senior Backend Engineer Candidate
- **Context**: Bulk Action Platform for CRM Application (Shipmnts Technical Assignment).
- **Key Talking Points**:
  - *"Welcome! In this walkthrough, I’m presenting the Bulk Action Platform designed to process large-scale batch operations on CRM entities (Contacts, Leads, Companies, etc.) with high throughput, horizontal scalability, and enterprise-grade reliability."*
  - *"Our core stack leverages **Python 3.12**, **Django 6**, **Django REST Framework**, **Celery**, **Redis 7**, and **PostgreSQL 17**."*
  - *"Beyond the core requirements, I have implemented all three optional enhancements: **Redis-based sliding-window rate limiting**, **distributed in-action email de-duplication**, and **future scheduling via Celery Beat**."*

---

## 2. Architecture & Modularity (0:45 - 2:00)
- **Visual**: Show `docs/architecture.md` diagram or `README.md` architecture layer.
- **Key Talking Points**:
  - **Strict Layered Architecture**:
    - **Thin Views**: Parse HTTP requests, validate serializers, delegate to services.
    - **Service Layer**: Owns business logic, rate limiting checks, transactions, and Celery dispatch.
    - **Repository Layer**: Exclusive owner of all database queries (`bulk_update`, `bulk_create`, `id__in`).
    - **Models**: Clean schemas, constraints, and indexes.
  - **Modular Strategy Pattern (`ActionStrategy`)**:
    - An abstract base class defining `validate_payload()` and `execute()`.
    - `BulkUpdateStrategy` dynamically inspects model metadata to safely update any arbitrary entity field.
    - Adding future actions (e.g., `BulkDeleteStrategy`, `BulkAssignOwnerStrategy`, `BulkExportStrategy`) requires zero modifications to views or tasks.
  - **Entity Agnosticism (`EntityRegistry`)**:
    - The platform is decoupled from any single model.
    - Show `EntityRegistry.register("lead", LeadRepository(), email_field="email")`.
    - Demonstrates that supporting `Contact`, `Lead`, `Company`, or `Opportunity` takes only 2 lines of code.

---

## 3. Scalability, Concurrency & Database Efficiency (2:00 - 3:30)
- **Visual**: Open `apps/bulk_actions/services/chunk_execution_service.py` and `config/celery.py`.
- **Key Talking Points**:
  - **Workload Partitioning (Chunking)**:
    - A 10,000-record batch is divided into 500-entity chunks.
    - Each chunk runs as an independent, stateless Celery task dispatched across worker processes or nodes.
  - **Zero N+1 Database Access**:
    - Records are retrieved using `id__in` in one round-trip per chunk.
    - Updates are applied using Django's `bulk_update(entities, fields=...)`.
    - Logs are flushed using `bulk_create(logs, batch_size=500)`.
  - **Atomic Counter Increments (`F()` expressions)**:
    - Multiple Celery workers update progress concurrently without row-lock contention or race conditions:
      `BulkAction.objects.filter(id=action_id).update(success_count=F("success_count") + count)`.
  - **Celery Reliability (Late Acknowledgment)**:
    - Configured `task_acks_late = True` and `task_reject_on_worker_lost = True`.
    - If a worker crashes or encounters an OOM mid-chunk, the task is redelivered rather than lost.
    - Paired with **Idempotent Chunk Execution** (`select_for_update()`, status guard), ensuring safe retries without double-counting.

---

## 4. Live Demonstration (3:30 - 5:00)
- **Visual**: Split screen with Terminal (running Celery workers) and Browser (Swagger UI / Django Admin / Postman).
- **Demo Steps**:
  1. **Show Seeded Database**:
     - Display 10,000 Contacts in Django Admin (`http://localhost:8000/admin/`).
  2. **Trigger Bulk Action via Postman or Swagger UI**:
     - Send `POST /api/bulk-actions/` targeting 1,000 contacts to update `status="archived"` and `age=35`.
     - Highlight Celery worker logs immediately picking up chunks in parallel.
  3. **Inspect Real-Time Progress & Stats**:
     - Call `GET /api/bulk-actions/{id}/` showing real-time `progress_percentage`.
     - Call `GET /api/bulk-actions/{id}/stats/` showing chunk breakdown (`total`, `completed`).
  4. **Highlight Deduplication**:
     - Show duplicate emails automatically marked as `SKIPPED`.
     - Inspect `GET /api/bulk-actions/{id}/logs/?status=SKIPPED`.
  5. **Demonstrate Rate Limiting (10,000 entities/minute per tenant)**:
     - Attempt to send another action exceeding the minute window.
     - Show HTTP `429 Too Many Requests` returning current usage and window limits.

---

## 5. Scheduling & Edge Cases (5:00 - 6:15)
- **Visual**: Show `apps/bulk_actions/tasks.py` (`process_scheduled_actions`) and Celery Beat terminal.
- **Key Talking Points**:
  - **Future Scheduling**:
    - Show `POST /api/bulk-actions/` with `"scheduled_at": "2026-11-22T23:15:00Z"`.
    - Action is marked `SCHEDULED`. Celery Beat periodically checks for due actions, runs the rate limiter check, and triggers chunking at the target timestamp.
  - **Fault Tolerance & Partial Failures**:
    - If a single record within a chunk fails validation, only that record is logged as `ERROR`. The remaining valid records commit cleanly, and `failure_count` is incremented atomically.
    - If an entire chunk encounters a database timeout, Celery retries it with exponential backoff.

---

## 6. Assumptions, Trade-offs & Wrap-up (6:15 - 7:00)
- **Key Talking Points**:
  - **Trade-off 1: Redis Sliding Window vs. Token Bucket**:
    - Chosen sliding window Lua script for strict per-minute entity cap accuracy across distributed nodes.
  - **Trade-off 2: In-Action Deduplication vs. Global Deduplication**:
    - Scoped email deduplication to the active `BulkAction` using Redis Sets (`bulk_action:<id>:seen_emails`) with TTL to ensure multi-worker isolation without unbounded memory growth.
  - **Trade-off 3: Chunk Size (500 records)**:
    - Balances PostgreSQL query payload size, memory footprint, and worker concurrency.
  - **Conclusion**:
    - Point reviewer to `README.md`, `Bulk_Action_Platform.postman_collection.json`, `docs/`, and `dump.sql`.
    - Thank the reviewer for their time!
