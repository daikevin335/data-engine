# Milestone 6: PostgreSQL job storage

Jobs are now stored in PostgreSQL when the API is started with a `DATABASE_URL`. A job submitted before a server restart can still be fetched after it. Without `DATABASE_URL` the API falls back to the in-memory store from Milestone 5, and logs a warning that jobs will be lost on restart.

## Running the database locally

```
docker run -d --name data-engine-postgres \
  -e POSTGRES_USER=data_engine \
  -e POSTGRES_PASSWORD=<choose a password> \
  -e POSTGRES_DB=data_engine \
  -p 127.0.0.1:5433:5432 \
  -v data-engine-pgdata:/var/lib/postgresql/data \
  postgres:17
```

- `127.0.0.1:` before the port exposes the database only to the local machine.
- The host port is 5433 because another Postgres container on this machine already uses 5432. The container still listens on 5432 internally.
- The named volume keeps the data when the container is removed. Deleting the volume (`docker volume rm data-engine-pgdata`) erases the database.
- The password is a local development value. It is passed through environment variables and is not stored in the repository.

Start the API against it, from the repository root:

```
export DATABASE_URL="postgresql+psycopg://data_engine:<password>@127.0.0.1:5433/data_engine"
uvicorn data_engine.api:build_app --factory --reload
```

## Components

| File | Purpose |
| --- | --- |
| `data_engine/pg_jobs.py` | `PostgresJobStore`: the same `create`, `get` and `update` methods as `JobStore`, backed by a `jobs` table through SQLAlchemy. |
| `data_engine/api.py` | `store_from_env()` picks the store; `build_app()` is the function uvicorn runs. |
| `tests/test_job_stores.py` | The same checks run against both stores, plus Postgres-only and restart checks. |

## The `jobs` table

| Column | Type | Notes |
| --- | --- | --- |
| `id` | string, primary key | 32-character hex id |
| `status` | string | `queued`, `running`, `succeeded` or `failed` |
| `params` | JSONB | the request: file, strategy, chunk size |
| `created_at` | timestamp with time zone | |
| `finished_at` | timestamp with time zone, nullable | |
| `seconds` | double precision, nullable | time the job took |
| `error` | text, nullable | the error type only |
| `result` | JSONB, nullable | the counts and per-group table |

## Design decisions

- **The API did not change.** The endpoints only call `create`, `get` and `update`, so swapping the store needed no endpoint changes. The Postgres store returns the same dictionaries as the in-memory one, with timestamps as ISO strings.
- **JSONB for `params` and `result`.** The parameters and results are small, nested and shaped differently per job. Storing them as JSON in a column avoids a table per shape and still lets Postgres query inside them later.
- **`build_app()` instead of a module-level `app`.** Importing `data_engine.api` used to create the app. If the app now connected to a database at import time, merely running the tests could open a connection. A factory function builds the app only when uvicorn asks for it, which is why the run command gained `--factory`.
- **Unknown field names are rejected.** `update(job_id, statsu="running")` raises `ValueError` instead of silently doing nothing.
- **Updating a job that does not exist raises `KeyError`**, as the in-memory store does.
- **The tables are created on startup (`create_all`).** This only creates a missing table; it cannot change an existing one. Changing the schema safely needs migrations (Alembic), which are not set up yet.

## Verification

The store tests run against Postgres only when `TEST_DATABASE_URL` points at a test database. Without it, those tests are reported as skipped, not passed.

```
docker exec data-engine-postgres psql -U data_engine -d postgres -c "CREATE DATABASE data_engine_test;"
export TEST_DATABASE_URL="postgresql+psycopg://data_engine:<password>@127.0.0.1:5433/data_engine_test"
python -m pytest -q
```

The tests **drop and recreate the `jobs` table**, so they refuse any database whose name does not end in `_test`. That rule has its own test.

What the tests check, for both stores unless noted:

- a new job is `queued` with a valid id, timestamp and empty result fields;
- `get` returns what was created, and `None` for an unknown id;
- `update` changes only the given fields and timestamps round-trip;
- results come back exactly, including floats such as 6978862.1899999995;
- updating an unknown job raises `KeyError`;
- changing a returned record does not change the stored one;
- Postgres only: a typo in a field name is rejected;
- Postgres only: a job is still there when read through a new store on the same database;
- Postgres only: through the API, a job submitted on one app can be fetched, with identical status and results, from a freshly built app on the same database.

The Postgres tests were checked by breaking the store on purpose: making `update` skip its commit failed four tests, and removing the unknown-job check failed one.

During development the suite and a live check ran against PostgreSQL 16. A job submitted to a running server was still returned, identically, after that server was stopped and started again.

## Limitations

- Schema changes need migrations, which are not set up.
- Job results are stored whole in one column. That is fine for the small group tables the engine produces, but not for large outputs.
- Old jobs are never deleted, so the table grows with use.
- The job still runs inside the web server process. A server restart in the middle of a job leaves it stuck in `running`. Celery and Redis address this in the next milestone.
- Credentials come from an environment variable, which is acceptable for development but not a secrets system.