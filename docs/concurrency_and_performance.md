# Concurrency, Performance & Reliability

This document explains the technical implementation of horizontal scaling, rate limiting, deduplication, and idempotency in the Bulk Action Platform.

---

## 1. Horizontal Scaling via Workload Chunking

When processing thousands or tens of thousands of records, single-worker execution risks memory exhaustion, worker timeouts, and blocking other priority workloads.

The platform partitions bulk actions into isolated chunks:

```
                    ┌─────────────────────────┐
                    │ 10,000 Contact Entities │
                    └────────────┬────────────┘
                                 │
                   Splits into 20 Chunks of 500
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
┌──────────────┐            ┌──────────────┐            ┌──────────────┐
│ Chunk 0 (500)│            │ Chunk 1 (500)│            │Chunk 19 (500)│
└──────┬───────┘            └──────┬───────┘            └──────┬───────┘
       ▼                           ▼                           ▼
Celery Task 0               Celery Task 1               Celery Task 19
 (Worker Node A)             (Worker Node B)             (Worker Node C)
```

- **Database State Tracking**: Each chunk is persisted in `bulk_action_chunks` with `chunk_index`, `start_index`, `end_index`, and `entity_ids`.
- **Independent Failure Domains**: A failure in Chunk 1 does not fail or abort Chunk 2.
- **Configurable Chunk Size**: Defaults to `500` records, but can be passed dynamically in the API request via `chunk_size` or globally configured in Django settings.

---

## 2. Multi-Tenant Rate Limiting (Redis Sliding Window)

Tenant workloads are constrained to **10,000 entities per minute** per `account_id`.

### Sliding Window Lua Implementation
Fixed-window counters suffer from burst vulnerabilities (e.g., 10,000 entities at 00:59 followed by 10,000 at 01:00). We employ an atomic Redis Lua script operating over a 60-second sliding window using a Redis Sorted Set:

```lua
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])      -- 60 seconds
local limit = tonumber(ARGV[3])       -- 10,000 entities
local requested = tonumber(ARGV[4])   -- entity count
local member_id = ARGV[5]

-- 1. Remove expired entries outside sliding window
local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Sum consumed entities in active window
local entries = redis.call('ZRANGE', key, 0, -1)
local current_total = 0
for _, entry in ipairs(entries) do
    local colon = string.find(entry, ":")
    if colon then
        local count = tonumber(string.sub(entry, 1, colon - 1))
        if count then
            current_total = current_total + count
        end
    end
end

-- 3. Check limit
if current_total + requested > limit then
    return {0, current_total, limit}
end

-- 4. Record consumption
local new_entry = tostring(requested) .. ":" .. member_id
redis.call('ZADD', key, now, new_entry)
redis.call('EXPIRE', key, math.ceil(window * 2))

return {1, current_total + requested, limit}
```

### Pre-Queue Verification
Rate limits are checked **before Celery tasks are enqueued**. If a request exceeds the account's quota, no tasks are queued and the API immediately returns HTTP `429 Too Many Requests`.

---

## 3. Distributed Email De-duplication

Within a single bulk action, duplicate entities sharing an email address must be skipped and logged as `SKIPPED`.

Because chunks execute concurrently across multiple worker processes, deduplication is coordinated via Redis sets:

1. **Redis Key Scope**: `bulk_action:{action_id}:seen_emails`
2. **Atomic Test-and-Set**:
   ```python
   is_new = redis_client.sadd(dedup_key, normalized_email)
   ```
   - If `is_new == 1`: The email has not been seen in this bulk action. Field modifications are applied and logged as `SUCCESS`.
   - If `is_new == 0`: The email has already been processed by this or another concurrent chunk worker. The record is skipped and logged with `status="SKIPPED"`.
3. **Automatic Cleanup**: A 24-hour TTL is set on the Redis key to prevent resource leaks.
4. **Tenant/Action Isolation**: Deduplication is scoped strictly to the current `bulk_action_id`, ensuring subsequent actions for the same tenant are never erroneously skipped.

---

## 4. Idempotency & Fault Tolerance

In distributed systems, Celery tasks may be redelivered due to worker crashes, network partitions, or broker reconnections. The platform ensures strict idempotency:

```python
with transaction.atomic():
    chunk = self.chunk_repo.get_by_id_for_update(chunk_id)
    if chunk.status == ChunkStatus.COMPLETED:
        return  # Safe no-op!
    self.chunk_repo.update_status(chunk.id, ChunkStatus.RUNNING)
```

1. **Row-Level Lock (`select_for_update`)**: Prevents duplicate concurrent executions of the same chunk.
2. **Terminal State Guard**: If a chunk has already attained `COMPLETED` status, execution immediately terminates as a no-op without re-incrementing counters or re-creating logs.
3. **Atomic Unit of Work**: Strategy execution, log generation (`bulk_create`), and counter increments (`F()`) commit inside a single atomic database transaction. If an error occurs halfway, all database changes for that chunk are automatically rolled back.

### Task Acknowledgment Strategy: Early Ack vs. Late Ack

| Aspect | Early Ack (`acks_late=False`) | Late Ack (`acks_late=True`) |
|---|---|---|
| **Acknowledgment Timing** | Immediately upon worker receiving the task from broker. | Only after the task function completes successfully. |
| **Worker Crash / OOM Behavior** | Task is **permanently lost**; stays in `RUNNING` or `PENDING` indefinitely. | Broker automatically **redelivers** task to an available worker. |
| **Safety Prerequisite** | Safe for non-idempotent tasks (e.g. sending emails). | Requires **idempotent** task design to prevent double-processing. |
| **Our Configuration** | ❌ Not suitable for batch pipelines. | ✅ **Active in platform** (`acks_late=True`). |

#### Why Late Ack is Required for Bulk Actions:
1. **Crash Resilience**: If a worker node crashes mid-batch (e.g. host restart, SIGKILL, out-of-memory error), the chunk task is redelivered rather than leaving the bulk action stalled forever.
2. **Guaranteed Idempotency**: Because chunk execution is fully idempotent, redelivery safely resumes:
   - If the previous worker committed before crashing, the redelivered task checks `if chunk.status == COMPLETED` and exits as a safe no-op.
   - If the previous worker crashed before commit, PostgreSQL rolled back uncommitted changes, allowing the new worker to execute cleanly from the start.
3. **Worker Loss Rejection**: Configured with `reject_on_worker_lost=True` so abnormal child worker termination triggers an immediate requeue.
4. **Fair Dispatching**: Configured with `worker_prefetch_multiplier=1` so worker processes do not prefetch chunks greedily while other workers are idle.

---

## 5. Database Efficiency & Zero N+1 Queries

| Concern | Anti-Pattern | Platform Implementation |
|---|---|---|
| **Entity Retrieval** | Fetching individual records in a loop: `Contact.objects.get(id=x)` | Single query per chunk: `Contact.objects.filter(id__in=chunk_entity_ids)` |
| **Model Updates** | Saving records in a loop: `entity.save()` | Single query: `repository.bulk_update(entities, fields)` |
| **Audit Logging** | Saving logs individually: `BulkActionLog.objects.create()` | Single query: `BulkActionLog.objects.bulk_create(logs)` |
| **Counter Tracking** | `action.success_count += 1; action.save()` | Atomic ORM expressions: `success_count = F('success_count') + count` |
