# Milestone 5: REST API

The API puts the processing engine behind HTTP. A client submits a job, the server answers immediately with a job id, the engine runs in the background, and the client then asks for the status and the results.

Run it from the repository root:

```
uvicorn data_engine.api:build_app --factory --reload
```

Without a `DATABASE_URL` environment variable, jobs are kept in memory. With one, they are stored in PostgreSQL ([postgres.md](postgres.md)).

FastAPI generates an interactive page at http://127.0.0.1:8000/docs where every endpoint can be tried from the browser.

## Components

| File | Purpose |
| --- | --- |
| `data_engine/api.py` | The endpoints, input checks, and the background function that runs a job. |
| `data_engine/jobs.py` | `JobStore`: where job records are kept (in memory for now). |
| `tests/test_api.py` | Endpoint, safety and benchmark-contract tests. |

## Endpoints

| Method and path | What it does | Success | Errors |
| --- | --- | --- | --- |
| `GET /health` | Reports that the server is up. | 200 | |
| `POST /jobs` | Starts a job. Body: `file` (a name inside the data folder), `strategy` (`baseline` or `chunked`, default `chunked`), `chunksize` (default 50,000). | 202 with `id` and `status` | 400 bad file name, 404 file not found, 422 invalid body |
| `GET /jobs/{id}` | Status, parameters, timestamps, seconds taken, and the error type if the job failed. | 200 | 404 unknown id |
| `GET /jobs/{id}/results` | The cleaning counts and the per-group table. | 200 | 404 unknown id, 409 job not finished or failed |
| `GET /benchmark` | Summaries of the saved benchmark reports in `benchmarks/`, sorted by file size, then chunk size. | 200 | |

A job moves through `queued`, `running`, then `succeeded` or `failed`.

## Design decisions

- **202 and a background run.** A large file takes seconds. The server answers at once and the client checks back, so no connection is held open for the length of the job.
- **The client sends a file name, never a path.** Otherwise `{"file": "/etc/passwd"}` or `"../../something"` would read arbitrary files on the server. `resolve_data_file` resolves the name (which also follows `..` and symlinks), then requires the result to be inside the data folder and to end in `.csv`. The check happens before the file is looked for, so a rejected request reveals nothing about files outside the folder.
- **A failed job exposes only the error type** (for example `ValueError`). Exception messages can contain server file paths. The full detail goes to the server log.
- **`GET /benchmark` serves measured results; it does not run a benchmark.** A benchmark takes minutes, and measuring while the server handles other requests would distort the numbers. The folder is fixed on the server, so the client chooses nothing. Raw per-run data is left out of the response, and a file that is not a valid report is skipped and logged. Running a benchmark on demand fits as a background job once Celery exists.
- **`JobStore` has three methods: `create`, `get`, `update`.** Today it is a dictionary guarded by a lock, because the background job writes to it while requests read it. PostgreSQL can replace it without changing the endpoints.
- **`create_app(data_dir, store, benchmarks_dir)` builds the app.** Tests can then use their own temporary folders and store instead of the real ones.

## Verification

From the repository root:

```
python -m pytest -v
```

The API tests cover:

- submitting a job and fetching its status and results, and both strategies giving the same answer through the API;
- rejection of `../` paths, nested `..`, absolute paths, symlinks that point outside the data folder, and non-`.csv` files. The test creates a real file outside the data folder, so the attack would succeed if the check were missing;
- a missing file (404), invalid strategy or chunk size (422), unknown job ids (404), asking for results before a job finishes (409);
- a failed job showing only the error type and no server path;
- `GET /benchmark` sorting, skipping broken files, leaving out raw data, and reading a report written by the real benchmark tool, which fails if the two formats drift apart.

The security tests were checked by breaking the code on purpose: removing the folder check made four tests fail, and returning the full exception message made one fail.

### Manual check (browser, Jersey City file)

Submitting `{"file": "JC-202609-citibike-tripdata.csv"}` on the `/docs` page returned 202. The status then showed `succeeded` in 0.188 s, and the results showed:

| Group | Count | Sum of durations (s) | Average (s) |
| --- | --- | --- | --- |
| casual, classic_bike | 8,509 | 6,978,862.19 | 820.17 |
| casual, electric_bike | 18,616 | 10,830,409.06 | 581.78 |
| member, classic_bike | 33,907 | 16,592,216.35 | 489.34 |
| member, electric_bike | 44,562 | 19,804,717.91 | 444.43 |

The counts add up to `rows_used` (105,594), which is 106,628 rows read minus 1,034 dropped by the duration filter. The casual classic-bike row matches the independent check made earlier.

## Limitations

- With the default in-memory store, jobs are lost when the server restarts and are not shared between server processes. Setting `DATABASE_URL` switches to PostgreSQL, which fixes both.
- The job runs inside the web server process. A long job competes with other requests for CPU, and a server restart kills it. Celery with Redis addresses this.
- No authentication, no limit on how many jobs run at once, no cancellation, and finished jobs are never removed, so memory grows with use.
- Only files in one data folder can be processed, chosen by the `DATA_ENGINE_DATA_DIR` environment variable (default `data`). The benchmark folder is set by `DATA_ENGINE_BENCHMARKS_DIR` (default `benchmarks`).