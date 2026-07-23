---
name: docker-compose-deployment
description: Deploy and verify Docker Compose stacks — compose up, health checks, container status, DB/data verification, API endpoint testing.
version: 1.0.0
tags: [docker, compose, deployment, health-check, containers]
---

# Docker Compose Deployment & Verification

## When to use

Load this skill when you need to:
- Deploy a Docker Compose stack locally
- Verify container health and service connectivity
- Audit deployment status (container state, API responses, DB data)
- Troubleshoot failed startups or misconfigured services

## Standard Deployment Workflow

### 1. Start the stack
```bash
cd <project_dir> && docker compose up -d
```

### 2. Verify container status
```bash
docker compose ps
# Check for "Up" status on all services
# Look for "Exited", "Restarting", or "Unhealthy"
```

### 3. Check service health
```bash
# API health endpoint
curl -s http://localhost:<port>/api/health
# Expected: {"status":"healthy"} or 200

# Web page
curl -s -o /dev/null -w "%{http_code}" http://localhost:<port>/
# Expected: 200
```

### 4. Verify database
```bash
# Check DB readiness
docker compose exec <db_service> pg_isready -U <db_user>

# List tables
docker compose exec -T <db_service> psql -U <db_user> -d <db_name> -c "\dt"

# Verify seed data
docker compose exec -T <db_service> psql -U <db_user> -d <db_name> -c "SELECT count(*) FROM <table>;"
```

### 5. Check app logs for errors
```bash
docker compose logs <app_service> --tail=30
```

### 6. Test API endpoints
```bash
# Health
curl -s http://localhost:<port>/api/v1/health

# Data endpoints (watch for trailing-slash redirects!)
curl -s http://localhost:<port>/api/v1/items/
```

## Common Pitfalls

### FastAPI trailing-slash redirect (307)
- `GET /api/v1/items` → **307 Temporary Redirect** to `/api/v1/items/`
- Clients that don't follow redirects get empty responses
- **Fix:** Always append trailing slash in curl/API calls, or set `redirect_slashes=False` in FastAPI router

### Database name mismatch
- `.env` may reference a different DB name than `docker-compose.yml` creates
- Always verify the actual DB name in compose file vs env file
- The app may fail to connect if `DATABASE_URL` points to a non-existent database

### Docker container internal networking
- **Symptom:** Script inside a container calls `http://localhost:8010/api/...` → `Connection refused`.
- **Root cause:** From inside a container, `localhost` resolves to the container itself, not the Docker host. The host-mapped port (8010) is not accessible from within the same Docker network.
- **Fix:** Use the container name + internal port from within the container:
  ```python
  BASE = "http://myapp-api-1:8000/api/v1"
  ```
- **Rule:** Scripts running inside a Docker container should address other containers by Docker network name and internal port, not the host-mapped port.

### Correct API endpoint discovery
- **Symptom:** Smoke tests fail with 404 because script calls wrong paths.
- **Root cause:** Endpoint paths in test scripts don't match the actual router definitions. Router prefixes are `admin/` not `resources/` or `bookings/`.
- **Fix — discover paths from source:**
  ```python
  # Read router files to find actual prefixes and paths
  # items.py: prefix = "/admin/items"
  # bookings.py: prefix = "/admin/bookings"
  # Correct paths: /api/v1/admin/items/, /api/v1/admin/bookings/
  ```
- **Rule:** Always verify endpoint paths against router source code before writing tests. The `@router.get/post` paths combined with the router's `prefix` give the full URL. Never guess — read the source.
- **Symptom:** `docker compose ps` returns `no configuration file provided: not found` from the project root.
- **Root cause:** Compose files (`docker-compose.yml`, `docker-compose.uat.yml`) live in a subdirectory (e.g., `project_dir/`), not the project root.
- **Fix:** Use explicit `-f` flags or `cd` to the directory containing the compose files:
  ```bash
  cd path/to/directory && docker compose up -d
  # OR
  docker compose -f path/to/docker-compose.yml -f path/to/docker-compose.uat.yml up -d
  ```
- **Verify:** `docker compose -f ... ps` to confirm services are listed.

### Service names vary by project
- **Symptom:** `docker compose up -d --build web` returns `no such service: web`.
- **Root cause:** The service name is defined in the compose file — it may be `api`, `app`, `backend`, etc.
- **Fix:** Check the actual service names first:
  ```bash
  docker compose ps
  ```
- Always use the correct service name for rebuilds: `docker compose up -d --build <service_name>`.

### Orphan containers
- Previous compose runs may leave orphaned containers
- Clean up: `docker compose up --remove-orphans`

### Environment variable issues
- Missing `.env` → app falls back to defaults or fails at startup
- Always verify `.env` exists and has required variables (DB URL, Redis URL, Qdrant URL, JWT secret, Stripe keys)
- Check `docker compose logs` for config-related startup errors

### Container crash-loop diagnosis
When a container keeps restarting (`Restarting (1) N seconds ago`):
```bash
# 1. Check status
docker ps --format "{{.Names}} {{.Status}}" --filter "name=<service>"

# 2. Read startup error
docker logs <container_name> --tail 50

# 3. Fix source code on host
# 4. Rebuild + restart
cd <project_dir> && docker compose build <service> && docker compose up <service> -d
# 5. Verify healthy
sleep 15 && docker ps --filter "name=<service>"
```
**Common crash-loop causes:**
- `ImportError` — missing module/function in `dependencies.py`
- `SyntaxError` — lost `):`, duplicate params, indentation errors
- `AttributeError` — enum value doesn't exist (e.g., `ServiceStatus.PENDING` when only `SCHEDULED` exists)
- Circular import — router imports from `main.py` which imports the router
- `slowapi` `KeyError: 'request'` — `@limiter.limit()` without `request: Request` param
- `slowapi` bare dict handler — `RateLimitExceeded` returning a dict causes 500; must return `JSONResponse(status_code=429)`

**Key rule:** Every code change requires `docker compose build <service>` before `up -d`. The container runs a cached image — host edits are invisible until rebuilt.
- Qdrant healthcheck may show "unhealthy" due to missing `wget` in the image
- The service may still be functional — verify with `curl -s http://localhost:6333/health`

### Static resource image naming convention mismatch
- **Symptom:** Seed `image_url` paths (`model_atto3.png`) don't match actual files (`model-atto3-blue.png`). Zero matches between seed data and filesystem.
- **Root cause:** Old seed data uses `model_{variant}.png` (underscore, no color). New files use `model-{variant}-{color}.{ext}` (hyphen, with color).
- **Fix — reconcile:**
  1. List actual files: `os.listdir("app/static/resources/")`
  2. Build model-to-file mapping dict
  3. Update all `image_url` values in seed JSON
  4. Set `null` for items without images
  5. Add new seed entries for models that have images but no DB records
  6. Verify every `image_url` references an existing file
- **Naming rule:** `brand-model-{variant}-{color}.{ext}` — ensures files are discoverable, sortable, and consistent with the resource they depict.
- **Color detection:** Use PIL to extract dominant non-background pixel color from the image, then map to a named color (silver, blue, black, white, yellow).
- **Google Drive source:** Copy via `shutil.copy()` (not `copy2`) to avoid xattr errors. Check subdirectories (`category_a/`, `category_b/`) if the file isn't at the root.
- **Reference:** See `references/resource-image-naming-convention.md`
- **Root cause:** Docker containers have isolated filesystems. Host files are NOT visible inside containers unless the Dockerfile `COPY` includes them or you explicitly copy them.
- **Fix (running container):** Copy files into the running container:
  ```bash
  docker compose cp path/on/host/file.ext <service>:/app/path/in/container/file.ext
  ```
- **Fix (durable):** Ensure `Dockerfile` COPY directive includes the asset directory (e.g., `COPY app/static/ app/static/`) so rebuilt containers automatically include the files.
- **Verify:** `curl -s -o /dev/null -w "%{http_code}" http://localhost:<port>/static/path/file.ext` → expect 200.

### Static asset staleness (CSS/JS/Jinja2 template content changes)
- **Symptom:** Page renders with broken or missing styles, or new UI components don't appear. `wc -c` on host vs container shows byte-count mismatch.
- **Root cause:** Files modified on the host are invisible inside the container until the Docker image is rebuilt. The `COPY . .` in the Dockerfile captured the old version.
- **Fast path — `docker cp` hot-deploy:**
  ```bash
  # Jinja2 templates — NO restart needed (Jinja2 reloads on each request)
  docker cp app/templates/profile.html myapp-api-1:/app/app/templates/profile.html

  # Python code (routers, schemas, services) — requires restart
  docker cp app/routers/customers.py myapp-api-1:/app/app/routers/customers.py
  docker compose restart api

  # Static assets (CSS/JS) — NO restart needed
  docker cp app/static/css/style.css myapp-api-1:/app/app/static/css/style.css
  ```
- **Slow path — `docker compose build --no-cache`:** Use when `docker cp` is impractical (batch changes, new files). BuildKit cache layers may not be fully invalidated, so the container can still have the old file. In that case, fall back to `docker cp` for the specific files that didn't update.
- **BuildKit pitfall:** `docker compose build --no-cache` can still serve cached intermediate layers for `COPY . .` directives. The Dockerfile layer cache is keyed on the entire directory hash — if only a few files changed, Docker may reuse the cached `COPY . .` layer. Verify the container has the new code with `docker exec <container> grep -n 'keyword' /app/path/to/file.py`. When `grep` shows the old content, the build cache wasn't invalidated. **Always fall back to `docker cp` for those files.**
- **Rule:** Prefer `docker cp` for hot-deploying individual file changes. Reserve `docker compose build` for dependency updates, new files, Dockerfile changes, or batch updates.
- **Verify:** `docker exec <container> grep -n 'keyword' /app/path/to/file.py` confirms the new code is deployed.
- **Quick fix (without rebuild):** `docker compose cp` to copy the updated file into the running container, but this is ephemeral — lost on container recreation. Use `docker compose build` for durability.

### Nginx reverse proxy with path prefix stripping (multi-app behind single entry)
- **Pattern:** Strip `/admin` prefix before proxying to admin app, restore on redirects with `proxy_redirect`.
- **Nginx config:**
  ```nginx
  location = /admin { return 301 /admin/; }
  location /admin/ {
      rewrite ^/admin(/.*)$ $1 break;
      proxy_pass http://admin-app;
      proxy_redirect / /admin/;
  }
  location /admin/static/ { rewrite ^/admin(/.*)$ $1 break; proxy_pass http://admin-app; }
  ```
- **Pitfall 1:** Bare `/admin` doesn't match `^/admin(/.*)$` → add `location = /admin { return 301 /admin/; }`
- **Pitfall 2:** FastAPI `RedirectResponse` returns absolute paths → browser gets `/dashboard` not `/admin/dashboard` → fix with `proxy_redirect / /admin/;`
- **Pitfall 3:** Template links/fetch() are absolute → pass `base_path` to templates: `{{ base_path }}/path`
- **Pitfall 4 (root_path anti-pattern):** Do NOT set `root_path="/admin"` on FastAPI app when using `proxy_redirect`. It causes double-prefixing (`/admin/admin/dashboard`). Use `proxy_redirect` alone.
- **Env:** Set `ADMIN_ROOT_PATH=/admin` for nginx, `ADMIN_ROOT_PATH=` for direct access
- **Reference:** See `references/nginx-reverse-proxy-with-path-prefix.md`

### Standalone Docker run (no Compose) — SQLite testing
When a quick local test deployment is needed without a full Compose stack, use `docker run` directly:

```bash
# Build image
cd <project_dir> && docker build -t <image_name> .

# Run with SQLite backend
docker run -d --name <container_name> -p 8000:8000 \
  -e DATABASE_URL="sqlite+aiosqlite:///./myapp.db" \
  -e REDIS_URL="redis://:REDIS_PASSWORD@<redis_container_name>:6379/0" \
  --health-cmd="curl --fail http://localhost:8000/api/v1/health || exit 1" \
  --health-interval=5s --health-timeout=3s --health-retries=3 \
  <image_name>
```

**Pitfall — `REDIS_URL` defaults to `localhost`:** If `REDIS_URL` env var is not set, the app falls back to `redis://localhost:***@redis-container-name:6379/0`).

**Pitfall — container name conflict:** If a previous run left a stopped container with the same name, `docker run --name <name>` fails with `Conflict`.

**Fix:** `docker rm -f <name>` before re-running.

**Pitfall — empty DB on container recreation:** When recreating a container with a volume-mounted SQLite DB, the DB file may be empty (0 bytes) or missing tables. The app starts but API calls fail with `OperationalError: no such table`.

**Fix:** After recreating the container, run migrations and seed data:
```bash
docker exec <name> python -m alembic upgrade head
docker exec <name> python /app/scripts/seed.py
```

**Verify:**
```bash
# Check health
docker inspect --format='{{.State.Health.Status}}' <name>
# Expected: healthy

# Check logs on crash
docker logs <name>
```

### Stale `__pycache__` ownership
- **Symptom:** `PermissionError` or `FileExistsError` when running `python3 -m py_compile` or importing modules on the host.
- **Root cause:** Docker containers create `__pycache__/` directories owned by `root:root` inside the container. When the host mounts the same directory, the cached `.pyc` files persist with root ownership, blocking host-side compilation.
- **Fix:** `find <dir>/__pycache__/ -name '*.pyc*' -delete 2>/dev/null` or `rm -rf <dir>/__pycache__/`.
- **Prevention:** Compile to a temp directory to avoid host `__pycache__` entirely: `TMPDIR=$(mktemp -d) && python3 -m py_compile --cfile=$TMPDIR/file.pyc path/to/file.py`.
- **Critical pitfall:** Modifying source code does NOT update running containers automatically.
- After code changes, the container still runs the **old image** until rebuilt.
- **Symptom:** API returns stale data or URLs (e.g., Stripe checkout URL instead of local payment page).
- **Fix:** `docker compose up -d --build <service>` to rebuild the image and recreate the container.
- **Verify:** Check the code inside the container matches committed source:
  ```bash
  docker compose exec <service> grep -n 'keyword' path/to/file.py
  ```
- Always rebuild after any code change to ensure the container runs the latest version.

### Schema drift: `user_id` vs `customer_id` column mismatch
- **Symptom:** API returns empty results or `IntegrityError` because ORM models reference `user_id` but DB columns are `customer_id`.
- **Root cause:** Historical naming inconsistency. Legacy models used `user_id` as the Python attribute but the DB was created with `customer_id` columns. SQLAlchemy silently maps `user_id` to a non-existent `user_id` column.
- **Fix — align ORM attribute to DB column:**
  ```python
  # Model uses Column() to map Python name to DB column
  customer_id: Mapped[uuid.UUID] = mapped_column(
      Column("customer_id", UUID(as_uuid=True)),
      ForeignKey("customers.id"), nullable=False, index=True
  )
  ```
  Alternatively, rename the Python attribute to `customer_id` everywhere (models, services, routers, seed scripts).
- **Bulk fix strategy:** Use search+replace all `user_id` → `customer_id` in relevant service files.
- **Rule:** Always verify ORM model column names match actual DB schema via `\d <table>`. A mismatch between model attribute and DB column is a silent killer — queries return empty sets without error.

### Alembic migration failures: bypass with direct SQL
- **Symptom:** Alembic chain broken (`revision` missing, state drift, `alembic check` fails) or new tables added outside migration workflow.
- **Root cause:** Auto-created tables bypass Alembic, or migration files get corrupted. The migration state no longer matches actual DB schema.
- **Fix — direct SQL migration script:**
  ```python
  from sqlalchemy import text
  from app.config import get_settings
  from sqlalchemy.ext.asyncio import create_async_engine

  async def create_tables():
      settings = get_settings()
      engine = create_async_engine(settings.database_url)
      async with engine.begin() as conn:
          # Create table
          await conn.execute(text("""
              CREATE TABLE IF NOT EXISTS plans (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  ...
              );
          """))
          # Seed data with valid UUIDs
          await conn.execute(text("""
              INSERT INTO plans (id, name, ...)
              VALUES ('a1000000-0000-0000-0000-000000000001', 'Plan Name', ...)
              ON CONFLICT (id) DO NOTHING;
          """))
  ```
  Deploy via `docker cp scripts/create_table.py <container>:/app/scripts/` + `docker exec <container> python3 /app/scripts/create_table.py`.
- **PostgreSQL UUID format requirement:** Table `id` columns with UUID type reject non-UUID strings. Values like `'plan-trial'` cause `InvalidTextRepresentationError: invalid input syntax for type uuid`.
  **Fix — use valid UUID format:**
  ```sql
  -- Valid UUIDs (v4 hex with hyphens):
  INSERT INTO plans (id, name, ...)
  VALUES ('a1000000-0000-0000-0000-000000000001', 'Trial Plan', ...),
         ('a1000000-0000-0000-0000-000000000002', 'Premium Plan', ...);
  ```
  **Generate deterministic UUIDs:** Use sequential hex patterns (`a1000000-0000-0000-0000-0000000000XX`) that PostgreSQL accepts. Avoid human-readable identifiers (`'plan-trial'`) for UUID columns.
  **Alternative:** Use `gen_random_uuid()` if deterministic IDs aren't required.
- **Settings import pattern for standalone scripts:** Use `from app.config import get_settings` then `get_settings().database_url`. Do NOT use `from app.config import Settings` — `Settings` is a class that requires instantiation. The `get_settings()` function is a cached singleton factory.
- **When to use:** Production DB with broken Alembic chain, quick schema updates, enum type creation, new tables without migrations, or when `alembic upgrade head` is unreliable.
- **Verify:** `docker exec <db_container> psql -U <user> -d <db> -c "\d <table>"` — confirm columns match ORM model.
- **Pitfall:** Enum type names must match exactly between DB and ORM model `sa.Enum(...)`. Mismatched names cause `sqlalchemy.exc.ProgrammingError: type does not exist`.

### Seed script: UnboundLocalError from shadowed imports
- **Symptom:** Seed script crashes with `UnboundLocalError: local variable 'Order' referenced before assignment`.
- **Root cause:** A module-level import (`from app.models.order import Order`) is re-imported inside a function body (`if existing: from app.models.order import Order`). Python treats the name as a local variable in that scope, causing references outside the block to fail.
- **Fix:** Remove or comment out the local imports — the module-level import already covers the whole file.
- **Rule:** If you see `UnboundLocalError`, search for duplicate `from ... import ...` statements inside the function body and remove them.

### Seed script schema alignment
- **Symptom:** Seed script fails with `UndefinedColumnError` on INSERT — e.g., `column "extra_col" of relation "my_table" does not exist`.
- **Root cause:** The seed script assumes columns that exist in the ORM model but NOT in the actual DB table. SQLAlchemy models often include fields that haven't been migrated, or the DB schema differs from the model.
- **Diagnosis — check actual DB schema:**
  ```bash
  # Get the real table columns
  docker exec <db_container> psql -U <user> -d <db> -c "\d <table>"
  ```
- **Fix:** Update INSERT statements to match actual DB columns. Do NOT assume ORM model columns exist in the DB.
- **Common mismatches:**
  - Timestamp columns (`created_at`, `updated_at`) have `DEFAULT now()` — can be omitted from INSERT
- **Rule:** Before writing INSERT statements, verify the target table schema with `\d <table>`. Use `DEFAULT` for auto-populated columns.
- **Verify:** After seeding, confirm counts with `SELECT count(*) FROM <table>`.
- **Reference:** See `references/seed-schema-alignment.md` for the full workflow.

### Auto-created tables missing from Alembic migrations
- **Symptom:** `get_or_create_X` or similar auto-create logic works at runtime, but `alembic/versions/001_initial.py` does not define the table. Fresh DB provision fails.
- **Root cause:** SQLAlchemy `declarative_base.metadata.create_all()` auto-creates tables at startup, bypassing Alembic. This creates drift between migration history and actual schema.
- **Fix:** Add the missing `CREATE TABLE` statements to the Alembic migration file.
- **Seeding auto-created tables:** When manually `INSERT`-ing into an auto-created table, include **ALL NOT NULL columns**. Discover required columns with:
  ```bash
  docker compose exec -T <db_service> psql -U <user> -d <db> \
    -c "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = '<table>' AND table_schema = 'public' ORDER BY ordinal_position;"
  ```
  Use `ON CONFLICT (id) DO NOTHING` for idempotent seeding.

### Seed script: FK cascade deletion order
- **Symptom:** Seed script fails with `IntegrityError: foreign key constraint — <table>` when trying to DELETE from parent tables (e.g., `users`, `products`).
- **Root cause:** Newer child tables have FKs to parent tables but are NOT in the seed script's deletion list.
- **Fix:** Query the DB for all FK dependencies, then delete in reverse topological order (leaf → root).
  ```bash
  # Discover all tables with FK → users
  docker compose exec -T <db_service> psql -U <user> -d <db> \
    -c "SELECT conrelid::regclass AS table_name FROM pg_constraint WHERE confrelid = 'users'::regclass AND contype = 'f';"
  # Repeat for other parent tables
  ```
  **Rule:** Always regenerate the deletion list whenever the schema evolves. Hard-coded model lists rot quickly.

### `docker cp` directory nesting
- **Symptom:** After `docker cp host_dir container:/path/dest_dir`, files appear inside a **nested** subdirectory: `/path/dest_dir/dest_dir/file.ext`.
- **Root cause:** `docker cp` of a directory preserves the source directory name, creating a nested copy. If the host `dest_dir/` already contains a `dest_dir/` subdirectory, a third level appears: `/path/dest_dir/dest_dir/dest_dir/file.ext`.
- **Fix — flatten the directory:**
  ```bash
  docker exec <container> bash -c "mv /path/dest_dir/dest_dir/* /path/dest_dir/ && rmdir /path/dest_dir/dest_dir"
  ```
- **Triple-nesting:** When the host directory already has a nested subdirectory with the same name, `docker cp` produces a third level. Flatten from the deepest level up:
  ```bash
  docker exec <container> bash -c "mv /path/d/d/d/* /path/d/d/ && rmdir /path/d/d/d && mv /path/d/d/* /path/d/ && rmdir /path/d/d"
  ```
- **Rule:** After `docker cp` of a directory, always check for nested subdirectories and flatten. Update any seed data or code that references file paths to match the actual nested or flattened location.
- **Verify:** `docker exec <container> ls /path/dest_dir/` — all files should be at the expected level, not nested.
- **Prevention:** Use `docker compose build` + `COPY` in Dockerfile instead of `docker cp` for durable static asset inclusion.
- **Recommendation:** Prefer **flat directory structures** (`/app/static/resources/`) over nested — more flexible for multi-brand support (e.g., `resources/brand1-*`, `resources/brand2-*`, `resources/brand3-*` all at one level). When `docker cp` creates nesting, flatten immediately and update seed paths accordingly.
- **Seed path update:** After flattening, update seed data `image_url` from `resources/resources/brand1-*.{ext}` → `resources/brand1-*.{ext}` (flat).

### Admin tool whitelist expansion
- **Symptom:** New tables (`customers`, `notifications`, etc.) appear in the DB but are missing from `db_admin.py` ALLOWED_TABLES.
- **Root cause:** Admin tools maintain an explicit `ALLOWED_TABLES` frozenset. New tables from migrations are not automatically included.
- **Fix:** Add new table names to `ALLOWED_TABLES` in `db_admin.py`, then `docker cp scripts/db_admin.py <container>:/app/scripts/`.
- **Rule:** After every schema change that adds or renames tables, audit and update admin tool whitelists. Use `docker cp` for immediate sync, then `docker compose build` for durability.

## Related Skills
- **Durable fix:** Rebuild the image: `docker compose build <service>`.
- **Rule:** Any file added to the project after the image was built is invisible to the container until rebuilt or `docker cp`'d.

### Circular FK workaround: drop constraint → delete → restore
- **Symptom:** Two tables have mutual FK references. No deletion order satisfies both constraints simultaneously.
- **Root cause:** Circular foreign keys between two tables (e.g., `table_a.fk_col → table_b` AND `table_b.fk_col → table_a`).
- **Fix — temporarily drop one constraint:**
  ```sql
  ALTER TABLE table_a DROP CONSTRAINT table_a_fkey_constraint;
  -- Now delete in any order
  DELETE FROM table_a WHERE parent_id = '<id>';
  DELETE FROM table_b WHERE parent_id = '<id>';
  ALTER TABLE table_a ADD CONSTRAINT table_a_fkey_constraint FOREIGN KEY (fk_col) REFERENCES table_b(id) ON DELETE CASCADE;
  ```
- **Rule:** When two tables reference each other, drop one FK constraint, perform the deletes, then restore it. Always verify the constraint is restored before proceeding.

### FastAPI `response_model` serialization mismatch
- **Symptom:** API endpoint returns `Internal Server Error` with `ResponseValidationError: Input should be a valid list`. Container logs show the actual dict response in the error.
- **Root cause:** `response_model=list[dict]` expects a bare list, but the function returns a dict with pagination wrapper like `{"items": [...], "total": N, "page": N}`.
- **Fix — remove or align `response_model`:**
  ```python
  # Wrong — enforces list-only response
  @router.get("/items/", response_model=list[dict])
  async def list_items(...):
      ...
      return {"items": items, "total": total, ...}  # dict, not list!

  # Right — no response_model (FastAPI infers)
  @router.get("/items/")
  async def list_items(...):
      ...
      return {"items": items, "total": total, ...}

  # Or — explicit dict model
  @router.get("/items/", response_model=ItemListResponse)
  async def list_items(...):
      ...
  ```
- **Rule:** When wrapping results in a pagination envelope (`items`/`total`/`page`), never use `response_model=list[...]`. Either omit `response_model` or define a proper response model with the pagination fields.
- **Diagnose:** Read `docker logs <container> --tail=30` — the `ResponseValidationError` includes the actual response dict, confirming the type mismatch.

### SQLAlchemy model↔DB schema mismatch: UndefinedColumnError
- **Symptom:** API endpoint fails with `sqlalchemy.exc.ProgrammingError: (asyncpg.exceptions.UndefinedColumnError): column "xyz" does not exist`.
- **Root cause:** The SQLAlchemy model defines a column (`mapped_column(String(20), nullable=True)`) that does NOT exist in the actual PostgreSQL table. This happens when:
  - A new column was added to the ORM model but no migration was run
  - The model was modified without running `alembic revision` + `alembic upgrade head`
  - The container image was rebuilt before the migration ran
- **Diagnose:** Check the actual DB schema:
  ```bash
  docker compose exec -T <db_service> psql -U <user> -d <db> -c "\d <table>"
  ```
  Compare the columns listed with the ORM model definition.
- **Fix options:**
  1. **Run migration:** `docker exec <api> alembic upgrade head`
  2. **Remove the column from model** (if not needed yet): Delete the `mapped_column` definition, update all references (`__repr__`, routers, services, seed scripts, test fixtures).
  3. **Manual ALTER TABLE** (quick fix): `docker exec <db> psql -U user -d db -c "ALTER TABLE <table> ADD COLUMN <col> <type>;"`
- **Rule:** Every ORM model change requires a corresponding DB migration. Never assume `mapped_column` declarations auto-create DB columns. Verify with `\d <table>` after any model change.
- **Cascading cleanup:** When removing a column from the model, update ALL references:
  - Router response dicts (e.g., `identifier` → removed from `list_configurable_items`)
  - Test fixtures (e.g., `identifier="GLR-..."` → removed from `conftest.py`)
  - Seed scripts (e.g., `identifier=...` → removed from INSERT)
  - `__repr__` method

### JS client fetching paginated API — template pattern
- **Symptom:** Template fetches `/api/v1/resource/` but the response is a dict `{"items": [...], "total": N}` not a bare array.
- **Root cause:** Router returns paginated envelope dict, but JS does `const data = await resp.json()` and iterates `data.forEach()`.
- **Fix:** Access `data.items` in the template:
  ```javascript
  const data = await resp.json();
  // data = {items: [...], total: 6, page: 1, has_next: false}
  const grid = document.getElementById('item-grid');
  grid.innerHTML = '';
  data.items.forEach(v => {
      // render card
  });
  ```
- **Pagination controls:**
  ```javascript
  pagination.innerHTML = `
    <button ${!data.has_prev ? 'disabled' : ''} onclick="loadItems(${data.page - 1})">← Prev</button>
    <span style="padding:8px">Page ${data.page}</span>
    <button ${!data.has_next ? 'disabled' : ''} onclick="loadItems(${data.page + 1})">Next →</button>
  `;
  ```
- **Rule:** Always check the actual API response structure before writing template JS. A quick `curl` of the endpoint reveals whether it returns a list or a paginated envelope.

### Debug loop: container API failure → diagnosis → fix → rebuild
When a container API endpoint fails:
```bash
# 1. Hit the endpoint — confirm failure
curl -s http://localhost:8010/api/v1/items/
# → "Internal Server Error" or empty response

# 2. Read container logs — find the exception
docker logs <container> --tail 30 | grep -A5 "Error\|Traceback\|Exception"

# 3. Identify error type:
#    ResponseValidationError → response_model mismatch → remove or fix response_model
#    UndefinedColumnError → column in model not in DB → check \d <table>
#    ImportError → missing import or bad path → check source
#    ValueError/TypeError → data shape mismatch → check service logic

# 4. Fix the source file on host

# 5. Rebuild + restart
docker compose up -d --build <service>

# 6. Verify fix
sleep 5 && curl -s http://localhost:8010/api/v1/items/
# → should return proper JSON
```
- **Common error→fix mapping:**
  | Error type | Cause | Fix |
  |---|---|---|
  | `ResponseValidationError` | `response_model` type mismatch | Remove `response_model` or define matching model |
  | `UndefinedColumnError` | Model has column not in DB | Run migration OR remove column from model |
  | `ImportError` | Missing/bad import path | Fix `from app.xxx import Y` |
  | `NoRowsFound` | Query expects row, none exists | Add `unique=False` or handle None |
  | `IntegrityError` | FK/unique constraint violation | Check existing data, use `ON CONFLICT` |

### Seed data injection workflow
- **Goal:** Populate database with test data for API testing and smoke tests.
- **Method 1 — SQL seed script (recommended):**
  ```bash
  # Create a seed SQL file on host
  # Copy to container
  docker compose cp seed.sql postgres:/seed.sql
  # Execute inside container
  docker compose exec -T postgres psql -U <user> -d <db> -f /seed.sql
  ```
- **Method 2 — Python seed script:**
  ```bash
  # Copy Python seed script
  docker compose cp seed_all.py api:/app/seed_all.py
  # Execute inside container
  docker compose exec api python3 /app/seed_all.py
  ```
  **Pitfall — async seed script timeout:** When using async SQLAlchemy sessions (`async_session_factory()`), a single session that commits 200+ records will time out after 60-180s. **Fix:** Break into multiple sessions that commit periodically (e.g., one session per table group). See `references/async-seed-script-debugging.md` for detailed debugging patterns.
- **Method 3 — `docker exec psql` for direct SQL:**
  ```bash
  docker compose exec -T postgres psql -U <user> -d <db> \
    -c "INSERT INTO ... ON CONFLICT DO NOTHING; ..."
  ```
- **Rule:** Seed scripts must delete existing data in reverse FK dependency order before inserting. Use `ON CONFLICT ... DO NOTHING` for idempotent inserts.
- **Credential discovery:** Smoke tests require valid auth tokens. The seeded user credentials (email, password) are defined in the seed script (e.g., `seed_all.py`). **Always search the seed scripts for `password` and `email` strings to find actual credentials.** Hardcoded passwords in seed scripts (`password123`) differ from test script assumptions.
- **Verify:** `SELECT count(*) FROM <table>` after seeding to confirm data was loaded.
- **Reference:** See `references/seed-fk-cascade.md` for FK cascade deletion order, `references/async-seed-script-debugging.md` for async seed script timeout debugging, and `references/admin-page-deployment-debug.md` for CSS staleness.

### Seed data consolidation — single master script
- **Goal:** Replace 15+ scattered seed scripts with one idempotent `seed_all.py` that creates tables, enums, and seeds all data.
- **`AsyncEngine.run_sync()` anti-pattern:**
  - **Symptom:** `AttributeError: 'AsyncEngine' object has no attribute 'run_sync'`
  - **Root cause:** `AsyncEngine` does NOT have `run_sync()`. This is a common mistake when trying to create tables from SQLAlchemy models inside an async seed script.
  - **Fix:** Use the project's `init_db()` from `app.database` which properly does `engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`:
    ```python
    from app.database import init_db
    await init_db()  # Creates all tables from SQLAlchemy models
    ```
  - **Alternative:** Use `engine.begin()` directly:
    ```python
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ```
- **Recovering files after destructive git operation:**
  - **Symptom:** `git reset --hard HEAD` (or similar) accidentally destroyed uncommitted changes. Container still has the latest code.
  - **Recovery:** Copy files from the running container back to the host:
    ```bash
    # Copy individual files from container /app/ to host
    docker cp <container>:/app/path/to/file.py ./project_dir/path/to/file.py
    ```
  - **Batch recovery:** Use `scripts/recover_from_container.sh`:
    ```bash
    ./scripts/recover_from_container.sh myapp-api-1 ./project_dir \
      app/models/plans.py app/routers/plans.py app/main.py ...
    ```
  - **Rule:** If you accidentally lose local changes and the container is still running with the latest code, `docker cp` is the fastest recovery path. Always verify with `git status --short` that the recovered files appear as modified.
  - **Prevention:** Commit before running any destructive git command. Use `git stash` if you need to switch branches without committing.
- **Enum creation order:** PostgreSQL enum types referenced in ORM models (e.g., `planstatus`, `planstype`) must be created BEFORE `metadata.create_all()` is called. Create them via raw SQL in a separate session:
  ```python
  async with async_session_factory() as session:
      for type_name, values in [
          ('planstype', ['trial', 'short', 'medium', 'long']),
          ('planstatus', ['pending', 'under_review', 'approved', ...]),
      ]:
          await session.execute(text(f"""
              DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') THEN
                      CREATE TYPE {type_name} AS ENUM ({','.join(f"'{v}'" for v in values)});
                  END IF;
              END$$;
          """))
      await session.commit()
  ```
- **Consolidation approach:**
  1. List all existing seed scripts and their target tables
  2. Build unified `seed_all.py` with sections for each table group
  3. Use deterministic UUID constants for reproducible seeding
  4. Add `clear_seed_data()` with correct FK deletion order
  5. Test via `docker exec <container> python seed/scripts/seed_all.py`
  6. Verify all table counts, then delete obsolete scripts
- **Reference:** See `references/seed-consolidation.md` for the full pattern, anti-patterns, and consolidation checklist.

## Verification Checklist

| Check | Command | Expected |
|---|---|---|
| All containers running | `docker compose ps` | All "Up" |
| API health | `curl /api/v1/health` | `{"status":"healthy"}` |
| DB tables exist | `psql -c "\dt"` | Table list returned |
| Seed data loaded | `SELECT count(*) FROM products` | count > 0 |
| Web page loads | `curl -w "%{http_code}" /` | 200 |
| No startup errors | `docker compose logs <app>` | No FATAL/ERROR lines |
| Container code matches source | `docker compose exec <svc> grep 'keyword' file.py` | Matches committed code |

## Post-Code-Change Workflow

After modifying source code:
1. `docker compose up -d --build <service>` — rebuild image + recreate container
2. `docker compose logs <service> --tail=10` — verify clean startup
3. `curl -s http://localhost:<port>/api/v1/health` — confirm service healthy
4. Re-test the affected endpoint to confirm the change took effect

### Deploy Loop
```bash
docker compose build api
docker compose up api -d
sleep 20
docker ps --filter "name=myapp-api"
```
After every code change, rebuild the image, restart the container, wait ~20s for startup, then verify health status is `Up (healthy)`.

### Model Change Rebuild Pattern

When SQLAlchemy model files change:
1. `docker compose build api` — rebuild image
2. `docker compose up api -d` — restart
3. `sleep 20 && docker ps` — wait + verify
4. Run seed/test scripts inside container

This loop ran 15+ times during a typical feature build.

## References
- `[scripts/reconcile_seed_images.py](scripts/reconcile_seed_images.py)` — Seed-to-image reconciliation: cross-reference, update, verify
- `[scripts/recover_from_container.sh](scripts/recover_from_container.sh)` — Recover files from running container (after `git reset --hard` or similar)
- `[references/dashboard-membership-card.md](references/dashboard-membership-card.md)` — Dashboard membership card: Jinja2 template + CSS + JS pattern, deployment verification
- `[references/seed-fk-cascade.md](references/seed-fk-cascade.md)` — Seed data: FK cascade deletion order
- `[references/seed-injection.md](references/seed-injection.md)` — Seed data injection workflow: SQL vs Python seed scripts, docker cp/exec patterns, idempotent ON CONFLICT inserts, UnboundLocalError from shadowed imports
- `[references/seed-injection-customer-scoped.md](references/seed-injection-customer-scoped.md)` — Customer-scoped seed injection: workflow, expected counts, orphan verification, common errors
- `[references/customer-id-column-mismatch.md](references/customer-id-column-mismatch.md)` — Schema drift: user_id vs customer_id column mismatch, ORM-to-DB alignment, bulk-replace strategy
- `[references/deployment-audit.md](references/deployment-audit.md)` — Deployment findings (trailing-slash, DB name mismatch, orphan containers)
- `[references/smoke-test-patterns.md](references/smoke-test-patterns.md)` — End-to-end smoke test patterns: auth, endpoint verification, error handling, internal container networking
- `[references/schema-drift-fix.md](references/schema-drift-fix.md)` — Schema drift diagnosis: UndefinedColumnError, model↔table mismatch, migration sync
- `[references/seed-schema-alignment.md](references/seed-schema-alignment.md)` — Seed script schema alignment: diagnosing UndefinedColumnError, ORM vs DB column mismatches, DEFAULT timestamp handling
- `[references/reseed-workflow.md](references/reseed-workflow.md)` — Re-seeding updated seed data: copy to container, build, run seed_all.py, verify
- `[references/premium-plan-feature.md](references/premium-plan-feature.md)` — Premium plan feature: DB table creation via direct SQL, UUID format requirement, progress stepper UX, plan selection workflow
- `[references/resource-image-loading.md](references/resource-image-loading.md)` — Resource image loading: host vs container filesystem, Wikimedia bot detection, SVG placeholders, Wikimedia API workflow (`ioprop=url`)
- `[references/wikimedia-api-image-downloads.md](references/wikimedia-api-image-downloads.md)` — Wikimedia Commons API: `ioprop=url` vs `iiurlmaxwidth`, 429 rate limiting, search→imageinfo→download workflow
- `[references/market-models-without-images.md](references/market-models-without-images.md)` — Models without images: placeholder handling, SVG fallbacks, naming conventions
- `[references/resource-image-naming-convention.md](references/resource-image-naming-convention.md)` — Resource image naming: `brand-model-{variant}-{color}` pattern, PIL color extraction, seed-to-image reconciliation, Google Drive copy via `shutil.copy()`
- `[references/static-image-orphan-cleanup.md](references/static-image-orphan-cleanup.md)` — Static image orphan cleanup: identify → remove from host → sync to container → remove orphans from container → verify HTTP 200
- `[references/feature-removal-checklist.md](references/feature-removal-checklist.md)` — Feature removal from full stack: model → service → router → template → test, with Docker hot-deploy verification
- `[references/db-credential-discovery.md](references/db-credential-discovery.md)` — DB credential discovery: finding actual passwords from env/compose files when container auth fails
- `[references/container-crash-loop-diagnosis.md](references/container-crash-loop-diagnosis.md)` — Container crash-loop: ImportError, circular import, slowapi, batch-edit pitfalls
- `[references/admin-page-deployment-debug.md](references/admin-page-deployment-debug.md)` — Admin page: CSS staleness, HTML-CSS class mismatch, service module syntax fixes

### Host Python → Docker psql seed pipeline (when execute_code sandbox cannot run subprocess)
- **Problem:** `execute_code` sandbox cannot run `subprocess.run(["docker", ...])` — it returns empty output. Also, packages like `bcrypt` may be missing from the sandbox Python environment.
- **Fix — write script to host, run via terminal:**
  1. Use `write_file()` to create a Python seed script in the project directory
  2. The script generates SQL on the host (with bcrypt/password hashing available)
  3. The script pipes SQL to Docker via `subprocess.run(["docker", "compose", "-f", "docker-compose.uat.yml", "exec", "-T", "postgres", "psql", "-U", "myapp", "-d", "myapp_uat"], input=sql, capture_output=True, text=True)`
  4. Run via `terminal("python3 path/to/seed_script.py")`
- **SQL escaping:** Use `s.replace("'", "''")` and wrap strings in single quotes. Use `NULL` (unquoted) for None values.
- **Verify after insert:** `docker compose exec -T postgres psql -U myapp -d myapp_uat -t -c "SELECT count(*) FROM users;"`
- **Idempotency check:** Query existing count first; skip or offset generation to avoid duplicates.
- **Name/email diversity:** Mix English (~55%) and Chinese pinyin (~45%) first/last names. Use local email domains (gmail.com, yahoo.com, icloud.com, hotmail.com, outlook.com, ymail.com, aol.com). Set login email to `testuser{N}@test.com` for discoverability.
- **Rule:** When seeding requires bcrypt hashing or Docker subprocess, always use host Python script + `terminal()`. Never try to run these from `execute_code`.

## Related Skills
### Persistent file logging (docker logs ring buffer is insufficient)
- **Problem:** `docker logs` captures stdout/stderr in a ring buffer. Logs are lost on container recreation and cannot be filtered by severity.
- **Fix:** Configure uvicorn `--log-config` with rotating file handlers + Docker named volume. See `references/docker-file-logging.md` for the complete pattern (Dockerfile, logging config, compose volume, access commands).
- **Key config:** `propagate: false` on uvicorn child loggers to prevent triple-duplication.
- **CRITICAL PITFALL — structlog `PrintLoggerFactory` ignores file handlers.** If you wire `structlog.PrintLoggerFactory()`, ALL structlog output goes to stdout only, completely bypassing any `RotatingFileHandler` you've configured. Use `structlog.stdlib.LoggerFactory()` OR configure file logging at the uvicorn level via `--log-config` instead. `--log-config` is the most reliable approach — it catches ALL output (structlog, uvicorn, Python logging) in the same file.
- **Triple-duplication trap:** If you add file handlers to BOTH `uvicorn.error` (parent) AND `uvicorn.error.access` (child), the child inherits parent handlers, producing 3x the lines. Always set `propagate: false` on `uvicorn.error` and `uvicorn.access` loggers.

## Related Skills
- `linux-remote-management`: Broader Docker/infrastructure management on Linux
- `hermes-s6-container-supervision`: s6-overlay container supervision inside Hermes Docker image