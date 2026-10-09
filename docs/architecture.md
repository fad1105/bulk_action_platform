# System Architecture

The Bulk Action Platform is designed according to a strict **Layered Architecture** with downward dependency flow:

```
HTTP Request
      │
      ▼
View / ViewSet         (Thin: HTTP validation, serializer mapping, response output)
      │
      ▼
Service Layer          (Business rules, orchestration, transactions, rate limiting)
      │
      ▼
Repository Layer       (Exclusive ORM database operations, bulk methods, atomic updates)
      │
      ▼
Django Models          (PostgreSQL 17 persistence schema)
```

---

## Architectural Layers & Responsibilities

| Layer | Component | Responsibility | Restrictions |
|---|---|---|---|
| **Presentation** | `BulkActionViewSet` | Validates HTTP requests, maps to DTOs, returns standard JSON / HTTP responses. | **Never** queries ORM directly or contains business rules. |
| **Service** | `BulkActionService`, `ChunkExecutionService` | Orchestrates repositories, enforces multi-tenant rate limits, splits chunks, schedules Celery tasks, handles idempotency. | **Never** accesses HTTP request objects or returns DRF responses. |
| **Strategy** | `BulkUpdateStrategy`, `StrategyFactory` | Implements pluggable execution strategies for entities. | Follows Modular Strategy Pattern. |
| **Registry** | `EntityRegistry` | Decouples action strategies from concrete models to achieve entity agnosticism. | Maps entity types to metadata and repositories. |
| **Repository** | `BulkActionRepository`, `BulkActionChunkRepository`, `BulkActionLogRepository`, `ContactRepository`, `LeadRepository` | Owns 100% of database queries. Utilizes `bulk_update()`, `bulk_create()`, `id__in`, and Django `F()` expressions. | **Never** makes business decisions or manages transactions. |
| **Model** | `BulkAction`, `BulkActionChunk`, `BulkActionLog`, `Contact`, `Lead` | Relational tables, indexes, constraints, and deterministic helper properties. | No business orchestration or external calls. |
| **DTO** | `BulkActionCreateDTO`, `StrategyResultDTO`, `ChunkExecutionDTO`, `BulkActionStatsDTO` | Typed frozen dataclasses for inter-layer data transfer. | Immutable data carrier crossing boundaries. |

---

## Entity Relationship Diagram

```mermaid
erDiagram
    BulkAction ||--o{ BulkActionChunk : "splits into"
    BulkAction ||--o{ BulkActionLog : "records"
    Contact ||--o{ BulkActionLog : "logged in"

    BulkAction {
        UUID id PK
        string account_id
        string entity_type
        string action_type
        json payload
        string status
        int total_count
        int success_count
        int failure_count
        int skipped_count
        datetime scheduled_at
        datetime created_at
        datetime updated_at
    }

    BulkActionChunk {
        bigint id PK
        UUID bulk_action_id FK
        int chunk_index
        int start_index
        int end_index
        json entity_ids
        string status
        text error_message
        datetime created_at
        datetime updated_at
    }

    BulkActionLog {
        bigint id PK
        UUID bulk_action_id FK
        string entity_id
        string status
        text error_message
        datetime created_at
    }

    Contact {
        bigint id PK
        string name
        string email
        int age
        string status
        datetime created_at
        datetime updated_at
    }

    Lead {
        bigint id PK
        string name
        string email
        string company
        string status
        datetime created_at
        datetime updated_at
    }
```

---

## Action Lifecycle & Execution Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant View as BulkActionViewSet
    participant ActionService as BulkActionService
    participant Limiter as RedisRateLimiter
    participant DB as PostgreSQL 17
    participant Queue as Celery (Redis Broker)
    participant Worker as ChunkExecutionService
    participant Strat as BulkUpdateStrategy
    participant Dedup as Redis Set (Seen Emails)

    Client->>View: POST /api/bulk-actions/
    View->>ActionService: create_bulk_action(DTO)
    ActionService->>Limiter: check_and_consume(account_id, total_count)
    alt Rate Limit Exceeded
        Limiter-->>ActionService: False (over 10,000/min)
        ActionService-->>View: RateLimitExceededException
        View-->>Client: 429 Too Many Requests
    else Allowed
        ActionService->>DB: BulkAction.create(), Chunk.bulk_create()
        alt Is Scheduled
            ActionService-->>View: Status SCHEDULED (No tasks queued)
        else Immediate
            ActionService->>Queue: Enqueue process_bulk_action_chunk for each chunk
            ActionService-->>View: Status RUNNING
        end
        View-->>Client: 201 Created
    end

    Note over Queue,Worker: Background Execution per Chunk
    Queue->>Worker: process_bulk_action_chunk(chunk_id)
    Worker->>DB: select_for_update() chunk
    alt Chunk Already Completed
        Worker-->>Queue: Skip (Idempotent No-op)
    else Chunk Pending/Running
        Worker->>Strat: execute(bulk_action, chunk, entity_ids)
        Strat->>DB: repository.get_by_ids(entity_ids) [id__in: 1 query]
        loop For each entity in chunk
            Strat->>Dedup: SADD bulk_action:<id>:seen_emails <email>
            alt Email already seen in this bulk action
                Strat-->>Strat: Mark SKIPPED
            else Unique email
                Strat-->>Strat: Apply field changes & Mark SUCCESS
            end
        end
        Strat->>DB: repository.bulk_update(entities, fields)
        Strat-->>Worker: StrategyResultDTO(success, failure, skipped, logs)
        Worker->>DB: log_repo.bulk_create_logs(logs)
        Worker->>DB: bulk_action_repo.atomic_increment_counts() [Django F()]
        Worker->>DB: chunk.status = COMPLETED
        Worker->>DB: evaluate_and_finalize_status(bulk_action_id)
    end
```
