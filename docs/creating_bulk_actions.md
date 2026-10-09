# Guide: Creating & Monitoring Bulk Actions

This guide provides practical, step-by-step instructions for creating, triggering, and monitoring bulk actions across the platform through the **Django Admin UI**, the **REST API**, and the **Python Service Layer**.

---

## Table of Contents
1. [Method 1: Django Admin (Bulk Action Form)](#method-1-django-admin-bulk-action-form)
2. [Method 2: Django Admin (Batch Selection Actions)](#method-2-django-admin-batch-selection-actions)
3. [Method 3: REST API (`POST /api/bulk-actions/`)](#method-3-rest-api-post-apibulk-actions)
4. [Method 4: Python Service Layer & Django Shell](#method-4-python-service-layer--django-shell)
5. [Monitoring Progress and Chunks](#monitoring-progress-and-chunks)
6. [Troubleshooting & Celery Worker Lifecycle](#troubleshooting--celery-worker-lifecycle)

---

## Method 1: Django Admin (Bulk Action Form)

The Django Admin allows staff users to configure and launch bulk actions without writing code or API calls.

### Steps:
1. Ensure your servers are running:
   ```bash
   make server    # Runs Django at http://localhost:8000
   make worker    # Runs Celery Worker with 4 concurrency
   ```
2. Navigate to **`http://localhost:8000/admin/`** and log in with your superuser credentials (`admin` / `admin123` or created via `make superuser`).
3. Under the **BULK ACTIONS** section, click **`Bulk actions`** and click the **`Add Bulk action`** button in the top-right corner.
4. Fill in the configuration form:

| Field | Description | Example |
|---|---|---|
| **Account id** | Tenant or operator identifier. | `admin_operations` |
| **Entity type** | Model to target. Dropdown dynamically loaded from `EntityRegistry`. | `Contact` or `Lead` |
| **Action type** | Strategy to execute. | `Bulk Update` |
| **Payload** | JSON object defining changes. | See examples below. |
| **Chunk size** | Records per Celery worker task (default: `500`). | `500` |
| **Scheduled at** | Optional future execution timestamp. Leave blank for immediate. | `2026-10-09 18:00:00` |

### Example Payloads:

#### Example A: Update all records in the table
```json
{
  "fields": {
    "status": "inactive"
  }
}
```

#### Example B: Update specific entity IDs with multiple fields
```json
{
  "entity_ids": [1, 2, 3, 4, 5, 10, 25],
  "fields": {
    "status": "archived",
    "age": 40
  }
}
```

5. Click **Save**:
   - The admin automatically delegates creation to [`BulkActionService`](file:///home/fenil/Documents/interview/bulk_action_platform/apps/bulk_actions/services/bulk_action_service.py).
   - Validates writable fields, checks tenant rate limits, chunks the records, and enqueues tasks to Celery.
   - Displays a success banner:
     ```text
     Successfully created Bulk Action <UUID> with 2 chunk(s) for 10 records.
     ```

---

## Method 2: Django Admin (Batch Selection Actions)

You can trigger a bulk action directly from list views by selecting rows with checkboxes.

### Steps:
1. In the Django Admin, go to **`ENTITIES`** -> **`Contacts`** (`/admin/entities/contact/`).
2. Select the checkboxes next to the contacts you wish to update.
3. Open the **Action** dropdown at the top of the table.
4. Select one of the available actions:
   - `Bulk update selected to 'active'`
   - `Bulk update selected to 'inactive'`
   - `Bulk update selected to 'archived'`
5. Click **Go**.
6. A `BulkAction` is automatically generated and dispatched via Celery, showing a success message:
   ```text
   Created Bulk Action <UUID> to update 25 contacts to 'archived' across 1 Celery chunk(s).
   ```

*(The same workflow is available under **Leads** with `Bulk update selected to 'qualified'` and `Bulk update selected to 'closed'`.)*

---

## Method 3: REST API (`POST /api/bulk-actions/`)

For programmatic integration, client applications can trigger actions over HTTP.

### Immediate Execution Example:
```bash
curl -X POST http://localhost:8000/api/bulk-actions/ \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "tenant_north_america",
    "entity_type": "contact",
    "action_type": "bulk_update",
    "payload": {
      "entity_ids": [101, 102, 103, 104],
      "fields": {
        "status": "verified",
        "age": 28
      }
    },
    "chunk_size": 500
  }'
```

### Scheduled Execution Example:
Add the ISO 8601 `scheduled_at` field:
```bash
curl -X POST http://localhost:8000/api/bulk-actions/ \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "tenant_north_america",
    "entity_type": "contact",
    "action_type": "bulk_update",
    "payload": {
      "fields": {
        "status": "dormant"
      }
    },
    "scheduled_at": "2026-10-09T18:00:00Z"
  }'
```
The action will be saved with status `SCHEDULED` and will be picked up by Celery Beat (`make beat`) at the scheduled time.

---

## Method 4: Python Service Layer & Django Shell

You can interact directly with the domain services in the Django shell or custom management scripts:

```bash
make shell
```

```python
from apps.bulk_actions.dtos import BulkActionCreateDTO
from apps.bulk_actions.services.bulk_action_service import BulkActionService

# 1. Initialize orchestration service
service = BulkActionService()

# 2. Build DTO
dto = BulkActionCreateDTO(
    account_id="internal_migration",
    entity_type="contact",
    action_type="bulk_update",
    payload={"fields": {"status": "synced"}},
    chunk_size=500,
)

# 3. Create, chunk, and dispatch
action = service.create_bulk_action(dto)
print(f"Action {action.id} dispatched with {action.chunks.count()} chunks for {action.total_count} entities.")
```

---

## Monitoring Progress and Chunks

### 1. In Django Admin
Open any Bulk Action in `/admin/bulk_actions/bulkaction/<id>/change/`:
- **Progress Display**: Real-time completion percentage (e.g. `85.0%`).
- **Counters**: Live totals for `total_count`, `success_count`, `failure_count`, and `skipped_count`.
- **Chunks Inline Table**: Lists all assigned `BulkActionChunk` entries with:
  - `Chunk Index`
  - `Start Index` and `End Index`
  - `Status` (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`)
  - `Error Message` (if any failure occurred)

### 2. Via REST API
- **Action Progress**:
  ```bash
  GET /api/bulk-actions/<id>/
  ```
- **Statistics & Chunk Breakdown**:
  ```bash
  GET /api/bulk-actions/<id>/stats/
  ```
- **Detailed Execution Logs (Filtered by Status)**:
  ```bash
  GET /api/bulk-actions/<id>/logs/?status=SKIPPED
  ```

---

## Troubleshooting & Celery Worker Lifecycle

### 1. Understanding `Chunk not found` Errors

If you start a Celery worker and see:
```text
ERROR: chunk_not_found
Chunk 1 not found.
```

#### Why this happens:
- **Test Database Disconnect**: Running automated test suites (`pytest`) creates temporary databases (e.g., `test_bulk_action_db`). If tests enqueue background tasks to the live Redis broker without test isolation, those IDs only exist in the temporary database.
- When tests finish, the test database is deleted.
- When your development worker (`make worker`) starts up, it reads those orphaned IDs from Redis and tries to query them in the development database (`bulk_action_db`), where they do not exist.

#### How this is resolved in our codebase:
1. **Automated Test Isolation**: `tests/conftest.py` configures Celery to run in **eager mode** (`CELERY_TASK_ALWAYS_EAGER = True`) during tests. Automated tests execute synchronously in-memory and **never** send tasks to the live Redis queue.
2. **Resilient Task Handling**: In [`tasks.py`](file:///home/fenil/Documents/interview/bulk_action_platform/apps/bulk_actions/tasks.py), nonexistent chunks raise [`ChunkNotFoundException`](file:///home/fenil/Documents/interview/bulk_action_platform/apps/core/exceptions.py). The task logs an `orphaned_chunk_task_discarded` warning and terminates gracefully rather than entering a failed retry loop.

### 2. Purging Orphaned Messages from Redis
If you ever need to manually clear pending messages from the Celery queue:
```bash
celery -A config purge -f
```
