# Setup & Operations Guide

This guide covers running the Bulk Action Platform locally, configuring Docker dependencies, managing background workers, and running tests.

---

## Prerequisites

- **Python**: 3.12+
- **Database**: PostgreSQL 17
- **Broker & Cache**: Redis 7+
- **Docker**: Optional (recommended for running PostgreSQL and Redis)
- **Make**: Available on Linux / macOS systems

---

## 1. Quick Start via Makefile

The project includes a comprehensive [`Makefile`](../Makefile) to automate all common development tasks:

```bash
# 1. Start Docker containers (PostgreSQL 17 and Redis 7 via Docker Compose)
make docker-up

# 2. Setup virtual environment and install dependencies
make venv
make install

# 3. Apply database migrations (or restore from dump.sql)
make migrate
# (Optional) Restore sample database directly from dump.sql:
# make db-restore

# 4. Create default admin superuser (admin / admin123)
make superuser

# 5. Seed sample contacts (if not restoring from dump.sql)
make seed

# 6. Start development servers in separate terminals:
make server       # Runs Django API & Admin on http://0.0.0.0:8000
make worker       # Runs Celery Worker with 4 concurrency
make beat         # Runs Celery Beat Periodic Scheduler
```

Access the Django Admin panel at: **`http://localhost:8000/admin/`**  
- **Username**: `admin`
- **Password**: `admin123`

---

## 2. Environment Variables

The platform uses sensible defaults for local development. In production, configure the following environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DB_NAME` | `bulk_action_db` | PostgreSQL database name |
| `DB_USER` | `postgres` | PostgreSQL username |
| `DB_PASSWORD` | `postgres` | PostgreSQL password |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery message broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery task result store |
| `REDIS_URL` | `redis://localhost:6379/2` | Redis URL for rate limiting & deduplication |
| `RATE_LIMIT_ENTITIES_PER_MINUTE` | `10000` | Max entities processed per account per minute |
| `DEFAULT_CHUNK_SIZE` | `500` | Default entities per Celery chunk task |
| `DEBUG` | `True` | Django debug toggle |
| `SECRET_KEY` | *(django secret)* | Django crypto key |

---

## 3. Running Services Separately

### Django Server
```bash
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000
```

### Celery Worker
Runs worker nodes listening to the default task queue:
```bash
source .venv/bin/activate
celery -A config worker --loglevel=INFO -c 4
```

### Celery Beat (Periodic Scheduler)
Triggers scheduled actions whose `scheduled_at` timestamp has arrived:
```bash
source .venv/bin/activate
celery -A config beat --loglevel=INFO
```

### Combined Development Worker + Beat
For local testing in a single terminal:
```bash
source .venv/bin/activate
celery -A config worker --beat --loglevel=INFO -c 2
```

---

## 4. Seeding Data for Load Testing

To simulate realistic high-volume bulk actions:

```bash
# Seed 1,000 contacts
python manage.py seed_data --count=1000

# Seed 10,000 contacts (tests rate limits and 20 Celery chunks)
python manage.py seed_data --count=10000
```

---

## 5. Running Tests

Run the full unit and integration test suite:

```bash
# Via Makefile
make test

# Or directly with pytest
source .venv/bin/activate
pytest -v
```

All 23 automated test scenarios verify:
- Sliding-window Redis rate limits (10,000/min)
- Workload chunking (500 items per chunk)
- Modular strategy pattern & entity agnosticism (`Contact` and `Lead`)
- Distributed email deduplication across chunk workers
- Scheduled execution with Celery Beat
- Idempotent task replays and fault-tolerance
- REST endpoints and error codes (`429`, `400`, `404`)
- OpenAPI 3.0 schema and Swagger/Redoc endpoints

---

## 6. Code Style & Linting

```bash
# Run Ruff lint checks
make lint

# Automatically format and fix issues
make format
```

---

## 7. Creating Bulk Actions & Troubleshooting

For full examples of triggering bulk actions through the **Django Admin UI**, **Batch List Actions**, and **REST API**, refer to the dedicated guide:
👉 **[Guide: Creating & Monitoring Bulk Actions](creating_bulk_actions.md)**

### Troubleshooting: Celery Worker `Chunk not found`
If starting `make worker` ever logs `Chunk not found`:
- This occurs when automated tests (`pytest`) run against an ephemeral test database and leave task IDs in the broker.
- Our test suite runs with Celery eager mode in `tests/conftest.py` to prevent queue contamination, and [`tasks.py`](../apps/bulk_actions/tasks.py) automatically discards nonexistent chunks without looping.
- To purge any stale messages from the queue manually:
  ```bash
  celery -A config purge -f
  ```

