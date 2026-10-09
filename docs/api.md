# REST API Reference

The Bulk Action Platform exposes a RESTful JSON API. All responses follow standard HTTP status codes.

---

## Interactive API Documentation (Swagger & Redoc)

The platform provides live interactive API explorers powered by `drf-spectacular`:

- **Interactive Swagger UI**: [**`http://localhost:8000/api/docs/`**](http://localhost:8000/api/docs/)
- **Redoc Documentation**: [**`http://localhost:8000/api/redoc/`**](http://localhost:8000/api/redoc/)
- **Raw OpenAPI 3.0 Schema**: [**`http://localhost:8000/api/schema/`**](http://localhost:8000/api/schema/)

You can test endpoints, inspect parameters, and download the full OpenAPI 3.0 specification directly from your browser.

---

## 1. Create Bulk Action

Initiates a bulk action. Validates parameters, evaluates rate limits, partitions workload into chunks, and either triggers tasks immediately or schedules them for future execution.

- **Method**: `POST`
- **Path**: `/api/bulk-actions/`
- **Content-Type**: `application/json`

### Request Body Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `account_id` | `string` | Yes | Tenant or account identifier (e.g., `"acc_001"`). |
| `entity_type` | `string` | Yes | Target entity type (e.g., `"contact"`, `"lead"`). |
| `action_type` | `string` | Yes | Strategy name (e.g., `"bulk_update"`). |
| `payload` | `object` | Yes | Action parameters. For `bulk_update`, requires `fields` and optional `entity_ids` / `filters`. |
| `payload.fields` | `object` | Yes | Key-value mapping of field names to new values. |
| `payload.entity_ids` | `array` | No | List of primary keys. If omitted, applies to all records matching filters or entity repository. |
| `chunk_size` | `integer` | No | Batch size per Celery task (default: `500`). |
| `scheduled_at` | `ISO 8601 string` | No | Scheduled timestamp (e.g., `"2026-10-09T15:00:00Z"`). If set, status starts as `SCHEDULED`. |

### Example Request

```bash
curl -X POST http://localhost:8000/api/bulk-actions/ \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "org_42",
    "entity_type": "contact",
    "action_type": "bulk_update",
    "payload": {
      "entity_ids": [10, 11, 12, 13],
      "fields": {
        "status": "archived",
        "age": 35
      }
    },
    "chunk_size": 500
  }'
```

### Success Response (`201 Created`)

```json
{
  "id": "c6214db6-444f-4dbe-a2ef-66a93010b9fe",
  "account_id": "org_42",
  "entity_type": "contact",
  "action_type": "bulk_update",
  "payload": {
    "entity_ids": [10, 11, 12, 13],
    "fields": {
      "status": "archived",
      "age": 35
    }
  },
  "status": "RUNNING",
  "total_count": 4,
  "success_count": 0,
  "failure_count": 0,
  "skipped_count": 0,
  "progress_percentage": 0.0,
  "scheduled_at": null,
  "created_at": "2026-10-09T01:50:22.123456Z",
  "updated_at": "2026-10-09T01:50:22.123456Z"
}
```

### Rate Limit Exceeded Response (`429 Too Many Requests`)

Returned when the account exceeds 10,000 entities in a 60-second window:

```json
{
  "error": "Rate limit exceeded",
  "account_id": "org_42",
  "limit_per_minute": 10000,
  "current_usage": 9800,
  "requested": 500
}
```

---

## 2. List Bulk Actions

Retrieves a paginated list of bulk actions with optional filtering.

- **Method**: `GET`
- **Path**: `/api/bulk-actions/`

### Query Parameters

| Parameter | Type | Description |
|---|---|---|
| `account_id` | `string` | Filter actions by tenant account ID. |
| `status` | `string` | Filter by status (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `SCHEDULED`). |
| `entity_type` | `string` | Filter by entity type (e.g. `contact`). |
| `page` | `integer` | Page number (default: `1`). |
| `page_size` | `integer` | Page size (default: `50`, max: `500`). |

### Example Request

```bash
curl -X GET "http://localhost:8000/api/bulk-actions/?account_id=org_42&status=COMPLETED"
```

### Success Response (`200 OK`)

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "c6214db6-444f-4dbe-a2ef-66a93010b9fe",
      "account_id": "org_42",
      "entity_type": "contact",
      "action_type": "bulk_update",
      "status": "COMPLETED",
      "total_count": 4,
      "success_count": 4,
      "failure_count": 0,
      "skipped_count": 0,
      "progress_percentage": 100.0,
      "scheduled_at": null,
      "created_at": "2026-10-09T01:50:22Z",
      "updated_at": "2026-10-09T01:50:25Z"
    }
  ]
}
```

---

## 3. Get Action Status & Progress

Returns real-time progress and status of a specific bulk action.

- **Method**: `GET`
- **Path**: `/api/bulk-actions/{id}/`

### Example Request

```bash
curl -X GET "http://localhost:8000/api/bulk-actions/c6214db6-444f-4dbe-a2ef-66a93010b9fe/"
```

### Success Response (`200 OK`)

```json
{
  "id": "c6214db6-444f-4dbe-a2ef-66a93010b9fe",
  "account_id": "org_42",
  "entity_type": "contact",
  "action_type": "bulk_update",
  "payload": { ... },
  "status": "RUNNING",
  "total_count": 1000,
  "success_count": 750,
  "failure_count": 10,
  "skipped_count": 40,
  "progress_percentage": 80.0,
  "scheduled_at": null,
  "created_at": "2026-10-09T01:50:22Z",
  "updated_at": "2026-10-09T01:50:27Z"
}
```

---

## 4. Get Action Statistics Summary

Provides a summary of counts and chunk lifecycle states.

- **Method**: `GET`
- **Path**: `/api/bulk-actions/{id}/stats/`

### Example Request

```bash
curl -X GET "http://localhost:8000/api/bulk-actions/c6214db6-444f-4dbe-a2ef-66a93010b9fe/stats/"
```

### Success Response (`200 OK`)

```json
{
  "id": "c6214db6-444f-4dbe-a2ef-66a93010b9fe",
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

## 5. Get Paginated Execution Logs

Returns individual entity result logs for the bulk action.

- **Method**: `GET`
- **Path**: `/api/bulk-actions/{id}/logs/`

### Query Parameters

| Parameter | Type | Description |
|---|---|---|
| `status` | `string` | Filter by log status (`SUCCESS`, `ERROR`, `SKIPPED`). |
| `page` | `integer` | Page number. |

### Example Request

```bash
curl -X GET "http://localhost:8000/api/bulk-actions/c6214db6-444f-4dbe-a2ef-66a93010b9fe/logs/?status=SKIPPED"
```

### Success Response (`200 OK`)

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 142,
      "bulk_action_id": "c6214db6-444f-4dbe-a2ef-66a93010b9fe",
      "entity_id": "104",
      "status": "SKIPPED",
      "error_message": "Duplicate entity with email 'alex@example.com' skipped.",
      "created_at": "2026-10-09T01:50:26Z"
    },
    {
      "id": 143,
      "bulk_action_id": "c6214db6-444f-4dbe-a2ef-66a93010b9fe",
      "entity_id": "109",
      "status": "SKIPPED",
      "error_message": "Duplicate entity with email 'maria@example.com' skipped.",
      "created_at": "2026-10-09T01:50:26Z"
    }
  ]
}
```
