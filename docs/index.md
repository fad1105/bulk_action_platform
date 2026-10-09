# Bulk Action Platform Documentation

Welcome to the technical documentation for the **Bulk Action Platform**. This platform is an enterprise-grade backend system designed to execute asynchronous, high-volume bulk operations across customizable domain entities safely, predictably, and with horizontal scalability.

---

## Documentation Index

1. [System Architecture](architecture.md)
   - Layered architecture principles (`Views -> Services -> Repositories -> Models`)
   - System component diagrams (Mermaid)
   - Entity-relationship model
   - Execution sequence flow

2. [Modular Strategy Pattern & Entity Agnosticism](strategy_pattern.md)
   - `ActionStrategy` interface and `BulkUpdateStrategy` implementation
   - `EntityRegistry` and decoupling strategies from concrete models
   - Guide: How to add a new entity (e.g., `Lead`, `Deal`) in < 10 lines of code
   - Guide: How to create a new action strategy (e.g., `BulkDeleteStrategy`)

3. [Concurrency, Performance & Reliability](concurrency_and_performance.md)
   - Workload chunking (500 records per task) & horizontal worker scaling
   - Sliding-window Redis rate limiter (10,000 entities/minute per tenant)
   - Distributed email deduplication via Redis sets
   - Idempotency guarantees & retry resilience
   - Database efficiency: batch queries (`id__in`), `bulk_update()`, `bulk_create()`, and atomic Django `F()` expressions

4. [REST API Reference](api.md)
   - Endpoint specifications (`POST`, `GET`, `/stats/`, `/logs/`)
   - Request and response payloads
   - Rate limit rejection response (`429 Too Many Requests`)
   - cURL examples and error codes

5. [Setup & Operations Guide](setup_guide.md)
   - Local prerequisites and Docker configuration (PostgreSQL 17 & Redis 7)
   - Virtual environment and dependency installation
   - Running Django server, Celery worker, and Celery Beat
   - Makefile command cheatsheet
   - Testing & benchmarking with the `seed_data` command

6. [Guide: Creating & Monitoring Bulk Actions](creating_bulk_actions.md)
   - Creating actions via Django Admin form & list selection actions
   - Creating actions via REST API & Python service layer
   - Monitoring chunk execution & error logs
   - Troubleshooting Celery worker lifecycle & orphaned task handling

7. [Loom Video Presentation Guide](loom_presentation_guide.md)
   - 5-to-7 minute structured walkthrough blueprint
   - Key talking points for system design, concurrency, and trade-offs
   - Step-by-step live demonstration script


---

## Quick Architecture Snapshot

```
HTTP Request
     │
     ▼
┌──────────────┐
│     View     │  (Thin: serialization, HTTP responses)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   Service    │  (Business rules, chunking, rate limiting, orchestration)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Repository  │  (Zero N+1 queries, bulk_update, bulk_create, atomic F())
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    Models    │  (PostgreSQL 17 persistence)
└──────────────┘
```
