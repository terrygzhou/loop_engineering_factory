---
name: fastapi-jinja2-feature-build
description: Build full-stack features in FastAPI + Jinja2 SSR — model, schema, router, service, template, JS, CSS, deployment.
version: 1.4.0
tags: [fastapi, jinja2, ssr, fullstack, feature-build]
---

# FastAPI + Jinja2 SSR Feature Build

## When to use
Building a feature in FastAPI + Jinja2 SSR. Covers: backend → API → frontend → deployment.

## Standard Workflow

Build features in this order — each step depends on the previous:

### Phase 1: Data Layer
1. **Model** — SQLAlchemy model with fields, constraints, relationships.
2. **Schema** — Pydantic schemas (Request/Response) for API layer.
3. **Service** — Business logic (CRUD, validation, auto-create).
4. **Router** — API endpoints, connected to service layer.

### Phase 2: Frontend (Tailwind CSS)

**All templates use Tailwind CSS via CDN.** No separate `.css` files unless the feature requires truly custom animations or vendor-specific overrides.

5. **Template** — Jinja2 HTML extending `base.html` (which loads Tailwind CDN + custom theme).
6. **JS** — Module (`static/js/<feature>.js`) that calls API and renders content.
7. **Tailwind Utilities** — Use utility classes for layout, spacing, typography, responsive design. No feature-specific CSS unless absolutely necessary.

**Responsive Breakpoints (mobile-first):**
| Breakpoint | Class Prefix | Width |
|------------|-------------|-------|
| Small | `sm:` | ≥640px |
| Medium | `md:` | ≥768px |
| Large | `lg:` | ≥1024px |
| Extra Large | `xl:` | ≥1280px |

## Template Structure

### base.html — Tailwind CDN + Theme Config

```html
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}App{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            primary: { 50: '#eff6ff', 100: '#dbeafe', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8' },
            success: '#22c55e',
            warning: '#f59e0b',
            danger: '#ef4444',
            dark: { bg: '#0f1117', card: '#161b22', border: '#30363d' },
          }
        }
      }
    }
  </script>
  {% block head %}{% endblock %}
</head>
<body class="bg-dark-bg text-gray-100 min-h-screen">
  {% block content %}{% endblock %}
  {% block scripts %}{% endblock %}
</body>
</html>
```

### Feature Template — Extend base.html

```html
{% extends "base.html" %}
{% block title %}<Page Title> - App{% endblock %}
{% block head %}
<!-- Only add feature-specific CSS if Tailwind utilities aren't enough -->
{% endblock %}
{% block content %}
<section class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="flex flex-col md:flex-row md:items-center md:justify-between mb-8">
        <h1 class="text-2xl font-bold text-white">{{ title }}</h1>
        {% block actions %}{% endblock %}
    </div>
    <div class="space-y-6">
        <!-- Feature content -->
    </div>
</section>
{% endblock %}
{% block scripts %}
<script src="/static/js/<feature>.js"></script>
{% endblock %}
```

**Rule:** Templates extend `base.html` and use Tailwind utility classes for all styling. Custom CSS files are only for features that require vendor-specific CSS (e.g., animations beyond Tailwind's scope, print styles, or complex transitions). Self-contained CSS blocks are a sign the page was built in isolation and needs standardization.

## Common UI Components (Tailwind)

### Card

```html
<div class="bg-dark-card border border-dark-border rounded-lg p-6 shadow-sm hover:shadow-md transition-shadow">
    <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-white">{{ item.name }}</h3>
        <span class="px-2 py-1 text-xs font-medium rounded-full bg-primary-500/20 text-primary-500">{{ item.status }}</span>
    </div>
    <p class="text-gray-400 text-sm">{{ item.description }}</p>
</div>
```

### Form

```html
<form id="form-{{ feature }}" class="space-y-6">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        {% for field in form_fields %}
        <div class="flex flex-col space-y-2">
            <label for="{{ field.id }}" class="text-sm font-medium text-gray-300">{{ field.label }}</label>
            <input type="{{ field.type }}" id="{{ field.id }}" name="{{ field.name }}"
                class="bg-dark-bg border border-dark-border rounded-md px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="{{ field.placeholder }}" {% if field.required %}required{% endif %}>
        </div>
        {% endfor %}
    </div>
    <div class="flex justify-end space-x-4">
        <button type="button" class="px-4 py-2 text-gray-300 bg-transparent border border-dark-border rounded-md hover:bg-dark-border transition-colors">Cancel</button>
        <button type="submit" class="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 transition-colors">Submit</button>
    </div>
</form>
```

### Data Table

```html
<div class="overflow-x-auto">
    <table class="w-full text-left text-sm">
        <thead class="text-xs uppercase bg-dark-bg border-b border-dark-border">
            <tr>
                {% for col in columns %}
                <th class="px-4 py-3 font-medium text-gray-300">{{ col }}</th>
                {% endfor %}
            </tr>
        </thead>
        <tbody class="divide-y divide-dark-border">
            {% for row in data %}
            <tr class="hover:bg-dark-card transition-colors">
                {% for cell in row %}
                <td class="px-4 py-3 text-gray-200">{{ cell }}</td>
                {% endfor %}
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
```

### Alert / Toast

```html
<!-- Success -->
<div class="flex items-center gap-3 p-4 bg-success/10 border border-success/30 rounded-lg text-success">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 9"></path></svg>
    <span>{{ message }}</span>
</div>

<!-- Error -->
<div class="flex items-center gap-3 p-4 bg-danger/10 border border-danger/30 rounded-lg text-danger">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
    <span>{{ error }}</span>
</div>
```

### Navigation Bar

```html
<nav class="bg-dark-card border-b border-dark-border px-6 py-4">
    <div class="flex items-center justify-between">
        <div class="flex items-center space-x-8">
            <a href="/" class="text-xl font-bold text-white">App</a>
            {% for item in nav_items %}
            <a href="{{ item.url }}" class="text-gray-300 hover:text-white transition-colors {{ 'text-white font-medium' if item.active else '' }}">{{ item.label }}</a>
            {% endfor %}
        </div>
        <div class="flex items-center space-x-4">
            <button class="text-gray-300 hover:text-white">🔔</button>
            <div class="w-8 h-8 rounded-full bg-primary-500 flex items-center justify-center text-sm font-medium text-white">U</div>
        </div>
    </div>
</nav>
```

### Responsive Grid Layout

```html
<!-- 1 col → 2 col → 3 col -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
    {% for item in items %}
    <div class="bg-dark-card border border-dark-border rounded-lg p-6 shadow-sm">
        <!-- item content -->
    </div>
    {% endfor %}
</div>
```

## ORM & SQLAlchemy Patterns

### SQLAlchemy eager-loading for 1:N relationships
When listing parent entities that have child collections (e.g., `Vehicle.images`), use `selectinload` or `joinedload` to avoid N+1 queries:
```python
from sqlalchemy.orm import selectinload
stmt = select(Vehicle).options(selectinload(Vehicle.images))
```

**CRITICAL: ALL queries that will be serialized by Pydantic into a schema containing a relationship field MUST eager-load that relationship.** This includes not just list endpoints, but also search, detail, and any endpoint where the response schema has a `List[ChildModel]` field. Omitting `selectinload` causes `MissingGreenlet` — Pydantic tries to lazily load the relationship during serialization, which fails in async context.

```python
# ✅ Correct — search endpoint loads images for serialization
result = await db.execute(
    select(Vehicle)
    .options(selectinload(Vehicle.images))
    .where(Vehicle.brand.ilike(f\"%{query}%\"))
    .limit(limit)
)

# ❌ Wrong — will crash with MissingGreenlet during Pydantic validation
result = await db.execute(
    select(Vehicle)
    .where(Vehicle.brand.ilike(f\"%{query}%\"))
    .limit(limit)
)
```

### Customer model `first_name`/`last_name` NOT NULL constraint
- **Symptom:** `NotNullViolationError: null value in column "first_name" of relation "customers" violates not-null constraint`
- **Root cause:** The `Customer` model has `first_name` and `last_name` as NOT NULL columns. When `mock_auth_service.register_user()` creates a Customer, it must pass these fields.
- **Fix — Update both `register_user()` and `UserCreate` schema:**
```python
# In mock_auth.py — register_user must accept and pass first_name/last_name
async def register_user(
    email: str, phone: Optional[str], password: str, db: AsyncSession,
    first_name: Optional[str] = None, last_name: Optional[str] = None
) -> User:
    customer = Customer(
        email=email,
        phone=phone,
        first_name=first_name or email.split("@")[0],  # fallback to email prefix
        last_name=last_name,
    )
```
```python
# In schemas/user.py — add optional fields
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
```
```python
# In routers/auth.py — pass through
user = await mock_auth_service.register_user(
    body.email, body.phone, body.password, db,
    first_name=body.first_name, last_name=body.last_name
)
```
- **Also update BOTH auth services:** The project has `app/utils/mock_auth.py` AND `app/services/auth_service.py`. Routers import `mock_auth_service` — fix the one that's actually imported.

### Model-Service-Schema-Router Field Alignment (CRITICAL)

**When a model uses `customer_id` as its FK, ALL four layers must use `customer_id` — NOT `user_id`:**

```
Model:  customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
Service: Booking.customer_id == customer_id  (not .user_id)
Schema:  customer_id: uuid.UUID  (not user_id)
Router:  customer_id: str = Depends(get_customer_id)  (not get_current_user_id)
```

**Common failure pattern:**
- `AttributeError: type object 'Model' has no attribute 'user_id'` — service/router/schema uses `user_id` but model has `customer_id`
- `pydantic_core.ValidationError: Field required [type=missing]` — schema has `user_id` but model returns `customer_id`
- `500 Internal Server Error` on list endpoint — service queries by wrong column

**Fix checklist when you see FK-related errors:**
1. Check model: `grep "customer_id\|user_id" app/models/<model>.py` — what does the model actually have?
2. Fix service: `sed 's/\.user_id/\.customer_id/g'` in the service file
3. Fix schema: Update all `user_id` → `customer_id` in `schemas/<model>.py`
4. Fix router: Change `get_current_user_id` → `get_customer_id` in all endpoints that scope to the model

**BEFORE writing any service code, verify ALL model attributes you'll reference:** Auto-generated code assumes conventions (`Vehicle.make`, `Order.total`, `Booking.start_date`) that rarely match actual column names. Always run:
```bash
grep '(\w+):\s*Mapped[' app/models/<model>.py
```
Then fix every mismatch. Common wrong→right mappings: `Vehicle.make`→`Vehicle.brand`, `Order.total`→`Order.total_price`, `Booking.start_date`→`Booking.date`, `Payment.customer`→(no FK, use `""`), `ServiceRecord.created_at`→`ServiceRecord.date`. See `speckit-implement` skill reference `model-attribute-mapping.md` for the full table.

### Admin service import ordering (forward-reference resolution crash)
- **Symptom:** Admin container crash loop with `ImportError`/`AttributeError` on startup.
- **Root cause:** Schema imports placed after SQLAlchemy core imports in admin service files. During async module initialization, forward-reference resolution fails.
- **Fix — import order in admin service files:** stdlib → SQLAlchemy → **ALL Pydantic schema imports** → business logic. Never put schema imports after function definitions.
- **Also remove phantom `*Detail` classes:** Verify the exact class name in the schema file before importing. Admin schemas sometimes define `*Detail` classes that are never used or don't exist.

### Main.py router import ordering (NameError crash)
- **Symptom:** `NameError: name 'X_router' is not defined` on container startup.
- **Root cause:** In `admin/main.py`, router imports are scattered with `include_router()` calls interspersed. A router referenced before its `from ... import` line crashes.
- **Rule — LOCAL import-before-use:** Each router must be imported on the line immediately before its `include_router()` call. Do NOT batch-import all routers at the top.
```python
# ✅ Correct — import right before use
from app.admin.routers.auth import router as auth_router
app.include_router(auth_router)

from app.admin.routers.audit_logs import router as audit_router
app.include_router(audit_router)
```

### Middleware import in admin main.py
- **Symptom:** `NameError: name 'RequestLoggingMiddleware' is not defined`
- **Fix:** Add explicit import near top of `admin/main.py`: `from .middleware import RequestLoggingMiddleware`

### Structlog middleware — event string required as first positional arg
- **Symptom:** `TypeError: _make_filtering_bound_logger.<locals>.make_method.<locals>.meth() missing 1 required positional argument: 'event'`
- **Root cause:** structlog's bound logger methods require an event string as the first positional argument before any keyword args. This crashes when used in exception handlers (`@app.exception_handler(HTTPException)`) because the HTTPException handler itself wraps in try/except.
```python
# ❌ Wrong — kwargs only, causes 500 on ANY HTTPException
logger.error(error_code=f"HTTP_{exc.status_code}", message=str(exc.detail), path=request.url.path)
# ✅ Correct — event string first, then kwargs
logger.error(f"HTTP_{exc.status_code}", message=str(exc.detail), path=request.url.path)
```
**Quick check:** If your container logs show `TypeError: ... missing 1 required positional argument: 'event'` on ANY request, grep for `logger\.(info|error|warning)\(` that lacks a positional string argument.

### Enum handling
When a model uses an enum for a status/role field, the DB column and the Python enum must align:
- Use `SAEnum(EnumType, values_callable=lambda e: [v.value for v in e])` for the column type
- Pydantic schemas should use `str` type (not the enum) unless you want enum validation
- Always check the actual DB column type with `\d <table>` before assuming

### Pydantic v2 date vs datetime mismatch (silent 500)
**Symptom:** API endpoint returns HTTP 500 with `ValidationError` in container logs:
```
pydantic_core.ValidationError: 1 validation error for <Schema>
  Datetimes provided to dates should have zero time - e.g. be exact dates
  [type=date_from_datetime_inexact]
```

**Root cause:** Model uses `DateTime(timezone=True)` in the DB column, but the Pydantic schema declares the field as `date`. Pydantic v2 strictly rejects `datetime → date` conversion when the datetime has a non-midnight time component (e.g. `2026-06-12T08:47:34+00:00`).

**Fix:** Match the schema type to the model type:
```python
# Model has:
start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))

# Schema must have (NOT date):
start_date: datetime    # ✅ works
# start_date: date       # ❌ ValidationError when time != midnight
```

**Quick diagnostic:** Check actual DB values:
```python
r = await session.execute(text("SELECT start_date FROM hirings LIMIT 1"))
print(r.scalar())  # If time component is non-zero, schema must use datetime
```

### FastAPI trailing slash 307 redirect

**Symptom:** `GET /api/v1/cart` returns 307 redirect to `/api/v1/cart/` (or vice versa). The endpoint exists but the client calling the path without trailing slash gets a redirect instead of the response.

**Root cause:** When a router has `prefix="/api/v1/cart"` and a route `@router.get("/")`, the combined path is `/api/v1/cart/` (with trailing slash). A request to `/api/v1/cart` (no trailing slash) gets a 307 redirect. This is FastAPI/Starlette default behavior.

**Fix — Use empty string `""` instead of `"/"` for the root route:**
```python
router = APIRouter(prefix="/api/v1/cart", tags=["cart"])

# ❌ Wrong — combined path is /api/v1/cart/, requests to /api/v1/cart get 307
@router.get("/", response_model=List[CartItem])

# ✅ Correct — combined path is /api/v1/cart, no trailing slash redirect
@router.get("", response_model=List[CartItem])
```

Apply to `@router.get("")`, `@router.delete("")`, etc. for any root-level route on a prefixed router. This applies to ALL HTTP methods (GET, POST, PUT, DELETE, PATCH).

### Query parameter `int | None` causes 422 — use `Optional[int]`

**Symptom:** `GET /api/v1/hires/available` returns 422 Unprocessable Entity with `"type": "int_parsing"` when no query param is provided, despite `Query(None)` default.

**Root cause:** Python union syntax `int | None` in `Query(None)` is not always handled correctly by FastAPI's OpenAPI schema generation. Some FastAPI versions fail to mark the parameter as optional in the generated schema, causing it to require the field and reject requests without it.

**Fix — Use `Optional[int]` from `typing`:**
```python
from typing import Optional

@router.get("/available")
async def available(
    dealership_id: Optional[int] = Query(None),  # ✅ correctly optional
    db: AsyncSession = Depends(get_db),
):
```

**Also: never use bare `UUID = None`** — always use `Optional[UUID] = Query(None)`.

### Literal route before parameterized route (CRITICAL)

**Symptom:** `GET /api/v1/hires/available` returns 404 or matches `/{id}` handler instead, producing 422 UUID parsing error.

**Root cause:** FastAPI matches routes in definition order. If `@router.get("/{id}")` is defined BEFORE `@router.get("/available")`, the literal string `"available"` gets captured as the `{id}` path parameter.

**Fix — Always define literal/static routes BEFORE parameterized ones:**
```python
@router.get("/available")    # ✅ literal first
async def available(...): ...

@router.get("/{id}")         # ✅ parameterized second
async def get(hire_id: UUID = Path(alias="id"), ...): ...
```

**See also:** `references/fastapi-route-shadowing.md` for the full debugging path.

### `docker cp` changes are wiped by `docker compose build`

**Symptom:** Endpoints added via `docker cp` to a running container disappear after `docker compose build` or `docker compose up -d --build`.

**Root cause:** `Dockerfile` has `COPY . .` which bakes the host directory into the image. `docker compose build` rebuilds from host disk, completely replacing the container filesystem. Files added via `docker cp` only exist in the running container layer.

**Rule:** Never use `docker cp` for Python source code changes that must persist. Always write files to the host filesystem first, then rebuild. Use `docker cp` ONLY for emergency template hotfixes on containers that won't be rebuilt.

**Also ensure `app/routers/__init__.py` exports ALL routers** that `main.py` imports. An orphaned router file on disk without a corresponding export in `__init__.py` causes `ImportError` on startup.

**See also:** `references/docker-cp-rebuild-loss.md` for full debugging path.

### Adding methods to existing service classes — indentation trap

**Symptom:** Container crash loop with `IndentationError: unexpected indent` at the line where you added `@staticmethod` or `def`.

**Root cause:** When adding a new method to an existing service class, the method was inserted AFTER the `service_instance = ServiceClass()` line at the bottom of the file. Python sees the indented method definition as code at module level (outside the class), causing `IndentationError`.

```python
class MyService:
    @staticmethod
    async def existing_method(db):
        ...

my_service = MyService()       # ← instantiation line

    @staticmethod              # ← WRONG: this is OUTSIDE the class now!
    async def new_method(db):  # IndentationError
        ...
```

**Fix — Always insert new methods BEFORE the instantiation line:**

```python
# Read the file and find the instantiation line
lines = content.split('\n')
insert_idx = next(i for i, l in enumerate(lines) if 'my_service = MyService()' in l)

# Insert new method before that line
new_method = '''    @staticmethod
    async def new_method(db):
        ...
'''
lines.insert(insert_idx, new_method)
```

**Verification:** After inserting, run `python3 -c "import ast; ast.parse(open('path/to/file').read())"` to confirm syntax before deploying.

**Quick diagnostic for crashes:** `docker logs <container> 2>&1 | grep -i "indentation"` — if you see `IndentationError` on a `@staticmethod` line, the method was placed after the class instantiation.

### Missing router import in main.py

**Symptom:** `GET /api/v1/notifications/preferences` returns 404 despite the router file existing in `routers/`. The router has endpoints defined but the app can't find them.

**Root cause:** Router file was created but never imported or registered in `main.py`.

**Fix — Add import and `include_router` in main.py:**
```python
# Add import with the other router imports
from app.routers import notification as notification_router
from app.routers import notification_preferences as notification_preferences_router

# Add mount near the other include_router calls
app.include_router(notification_router.router)
app.include_router(notification_preferences_router.router)
```

**Quick diagnostic:** `grep -rn "notification" main.py` — if nothing returns, the router is unmounted.

### Template JS field mapping mismatch with API response

**Symptom:** Detail page stuck on "Loading..." with no console errors. Template JS fetches data from API but never renders content.

**Root cause:** Template JS references fields like `v.retail_price`, `v.battery_capacity_kwh`, `v.drive_type` but the API returns `v.price`, `v.battery_kwh`, `v.drivetrain`. The field references silently evaluate to `undefined`, so conditional checks like `if (v.retail_price)` fail and nothing renders.

**Fix — Verify actual API response fields against template references:**
```bash
# Get actual API response structure
curl -s "http://localhost:8010/api/v1/vehicles/{id}" | python3 -m json.tool | grep '"key"'
```
Then update template JS to use the EXACT field names from the API response.

**Prevention:** Before writing template JS, always check the actual Pydantic response schema to confirm field names. The schema field names dictate what the JS receives.

### Pagination non-determinism with identical timestamps
**Symptom:** Paginated list returns identical items across pages (page 1 = page 2). `total` field is correct but `items` don't shift.

**Root cause:** Seed data created in bulk shares identical `created_at` timestamps. `ORDER BY created_at DESC` alone gives non-deterministic ordering — the database returns rows in arbitrary physical order when sort keys are equal, so `OFFSET` doesn't reliably skip distinct rows.

**Fix — Always add `Model.id.asc()` as secondary sort key:**
```python
# ❌ Wrong — unstable when timestamps are identical
query = query.order_by(Model.created_at.desc())

# ✅ Correct — deterministic even with identical timestamps
query = query.order_by(Model.created_at.desc(), Model.id.asc())
```

**Also fix:** When the model has no `created_at` column (e.g. `ServiceRecord` has `date`), use the model's actual date column as primary sort:
```python
query = query.order_by(ServiceRecord.date.desc(), ServiceRecord.id.asc())
```

**See also:** `references/admin-dashboard-pagination-debug.md` for full investigation and the `with_only_columns()` mutation trap.

### Enum-to-string comparison for status transitions
**Symptom:** Status transition validation always fails — `new_status not in valid_transitions.get(old_status, [])` never matches because `old_status` is `VehicleUnitStatus.DELIVERED` (enum) not `"delivered"` (str).

**Fix — Convert enum to lowercase string before comparison:**
```python
# ❌ Wrong — enum vs string never matches
old_status = unit.status  # <VehicleUnitStatus.DELIVERED: 'delivered'>

# ✅ Correct — normalize to lowercase string
old_status = str(unit.status).split(".")[-1].lower()  # "delivered"

# Then compare with lowercase strings
if new_status.lower() not in valid_transitions.get(old_status, []):
    raise HTTPException(status_code=422, detail=f"Invalid transition...")
```

### Pydantic empty-string rejection for date/datetime fields
**Symptom:** `pydantic_core.ValidationError: Input should be a valid datetime or date, input is too short [type=datetime_from_date_parsing, input_value='', input_type=str]`

**Root cause:** Service code passes empty string `""` for a nullable date/datetime field. Pydantic v2 rejects empty strings for datetime types — they must be `None` or a valid date/datetime value.

**Fix — Pass the raw DB value (None or date), not `""`:**
```python
# ❌ Wrong — empty string rejected by Pydantic
delivery_eta=""  # raises ValidationError

# ✅ Correct — pass None or the actual date
delivery_eta=u.eta_date  # None or datetime.date
```

### Pydantic `str` schema field — endpoint calls `.tzinfo` (AttributeError)
**Symptom:** `500 Internal Server Error` on POST/PUT endpoints with date fields. Container logs show:
```
AttributeError: 'str' object has no attribute 'tzinfo'
```

**Root cause:** Pydantic schema declares the date field as `str` (e.g., `booking_date: str = Field(...)`), but the endpoint code treats it as a `datetime` object — calling `.tzinfo`, `.replace(tzinfo=None)`, or comparing with `datetime.now()`. Pydantic validates the string format on ingress but does NOT auto-convert `str` to `datetime`.

**Fix — Parse the string to datetime before any datetime operations:**
```python
# Schema declares: booking_date: str
# ❌ Wrong — crashes: 'str' object has no attribute 'tzinfo'
booking_date = data.booking_date
if booking_date.tzinfo is not None:
    booking_date = booking_date.replace(tzinfo=None)

# ✅ Correct — parse first, THEN handle timezone
try:
    booking_date = datetime.datetime.fromisoformat(data.booking_date)
except ValueError:
    raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
if booking_date.tzinfo is not None:
    booking_date = booking_date.replace(tzinfo=None)
```

**Apply to BOTH create and update endpoints.** The same pattern applies when the schema uses `str | None` for an optional date field — check `if data.booking_date is not None:` before parsing.

**Prevention:** Consider using `date` or `datetime` types in Pydantic schemas instead of `str` — Pydantic v2 auto-parses ISO 8601 strings into proper datetime objects. Use `str` only when you intentionally want raw string handling.

### localStorage key consistency across templates
**Symptom:** Template loads but API calls return 401 "Could not validate credentials". Console shows auth token exists but fetches don't include the `Authorization` header.

**Root cause:** Different templates save/retrieve the JWT token under different `localStorage` keys:
- `signin.html` saves as `localStorage.setItem('access_token', data.access_token)`
- `book_test_drive.html` checks `localStorage.getItem('jwt_token')` — **mismatch, always returns `null`**

**Fix — Standardize on a single key name across ALL templates:**
```js
// ✅ Standard key — use consistently everywhere
localStorage.setItem('access_token', data.access_token);
var token = localStorage.getItem('access_token');

// ❌ Wrong — mismatched keys cause silent auth failures
localStorage.setItem('jwt_token', data.access_token);  // signin saves as 'jwt_token'
var token = localStorage.getItem('access_token');       // but other pages check 'access_token'
```

**Audit command to find mismatches:**
```bash
grep -rn "localStorage\.\(get\|set\)Item.*token" app/templates/
```
All occurrences must use the SAME key name. The `window.fetch` shadow in `base.html` auto-injects from `access_token` — if any template uses a different key, the shadowed fetch won't find it.

### UUID foreign keys
- Always use `ForeignKey(\"<table>.id\")` with the fully qualified table name
- Use `mapped_column(ForeignKey(\"...\"))` not just `mapped_column(UUID)`
- When querying across relationships, use `.where(Model.customer_id == UUID(cust_id))` not `.where(Model.customer_id == cust_id_str)`

### List endpoint: Pydantic schemas in dict returns require `.model_dump()`
**Symptom:** `TypeError: 'PydanticModel' object is not subscriptable` when iterating over list response items in JS templates.

**Root cause:** Service method builds a `dict` with `"items": [PydanticModel(...), ...]`. FastAPI serializes the dict but the list still contains Pydantic instances, not dicts. JS `for...of` or `.map()` on the response gets Pydantic objects, not plain dicts.

**Fix — Call `.model_dump()` on each schema instance before placing in dict:**
```python
# Service returns dict
async def list_customers(db, ...) -> Dict[str, Any]:
    result = await paginate(db, query, ...)
    return {
        # ✅ Serialize each ORM object through schema, then .model_dump() to dict
        "items": [AdminCustomerResponse(
            id=str(c.id), first_name=c.first_name, ...
        ).model_dump() for c in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
    }

# ❌ Wrong — returns list of Pydantic instances inside dict
"items": [AdminCustomerResponse(id=str(c.id), ...) for c in result["items"]]
```

**Rule:** When a service returns `dict[str, list]` (not a typed Pydantic model), you MUST call `.model_dump()` on each Pydantic schema in the list. `response_model` on the router can handle direct Pydantic returns, but it cannot serialize Pydantic instances nested inside a plain `dict`.

### Detail endpoint: `db.get()` does NOT eager-load relationships in async
**Symptom:** `500 Internal Server Error` on detail endpoint (e.g. `/api/admin/vehicle-units/{id}`). List endpoint works fine. Container logs show `MissingGreenlet` or similar async lazy-load error.

**Root cause:** `await db.get(Model, id)` uses the identity map and does NOT apply `selectinload()`. When the service method accesses `model.relationship` (e.g. `unit.vehicle`) after `db.get()`, SQLAlchemy attempts a lazy-load in async context, which crashes.

**Fix — Replace `db.get()` with `select().options(selectinload(...))`:**
```python
# ❌ Wrong — lazy-loads relationship in async, crashes
unit = await db.get(VehicleUnit, UUID(unit_id))
vname = unit.vehicle.name  # MissingGreenlet!

# ✅ Correct — eagerly loads relationship before access
from sqlalchemy.orm import selectinload
result = await db.execute(
    select(VehicleUnit)
    .options(selectinload(VehicleUnit.vehicle))
    .where(VehicleUnit.id == UUID(unit_id))
)
unit = result.scalar_one_or_none()
```

**Also fix enum serialization on detail endpoints:** The `_to_dict()` helper may return `unit.status` as an enum object. Always extract `.value` for string fields:
```python
# ❌ Wrong — returns VehicleUnitStatus.DELIVERED enum
"status": unit.status

# ✅ Correct — returns "delivered" string
"status": unit.status.value if hasattr(unit.status, 'value') else str(unit.status)
```

### List endpoint: ORM objects in dict values must be serialized
**Symptom:** `PydanticSerializationError: Unable to serialize unknown type: <class 'app.models.XXX.Model'>` when a GET list endpoint returns `{\\\"items\\\": [orm_obj1, orm_obj2, ...]}`.

**Root cause:** When a service method returns a `dict` containing ORM objects, Pydantic's `response_model` serialization tries to convert the dict values but cannot serialize raw ORM instances. This differs from `from_attributes` on model classes, which works on direct return values.

**Fix:** Serialize ORM objects to dictionaries in the service layer:
```python
async def list_feedback(customer_id: str, db: AsyncSession, ...) -> dict:
    query = select(ServiceFeedback).where(...)
    result = await db.execute(query)
    items = result.scalars().all()

    # ✅ Serialize explicitly — Pydantic can't handle ORM objects in dict values
    items_dict = [
        {
            \\\"id\\\": str(i.id),
            \\\"customer_id\\\": str(i.customer_id),
            \\\"overall_rating\\\": i.overall_rating,
            \\\"created_at\\\": i.created_at,
        }
        for i in items
    ]
    return {\\\"items\\\": items_dict, \\\"total\\\": total, \\\"page\\\": page, \\\"page_size\\\": page_size}
```

**When this happens:** Any service method that returns `dict[str, list[ORMObject]]` instead of a Pydantic model instance. The response_model on the router endpoint cannot auto-convert ORM objects nested inside dictionaries.

**Quick check:** If your list endpoint returns raw SQLAlchemy objects inside a dict, add the serialization step. If it returns a Pydantic model (e.g., `List[ResponseModel]`), `from_attributes` handles it automatically.

### Router endpoints returning ORM objects with `response_model` — use `.model_validate()`
**Symptom:** `500 Internal Server Error` on detail endpoints (e.g. `GET /api/v1/garage/invoices/{id}`) despite `response_model=InvoiceResponse` being set. Container logs show `PydanticSerializationError: Unable to serialize unknown type`.

**Root cause:** The router handler returns `return await service.get_invo

### `str(None)` produces `"None"` — use conditional or explicit check
**Symptom:** `str(body.order_id)` when `body.order_id` is `None` produces the string `"None"` instead of `None`. This creates DB records with `order_id="None"` which then fail UUID parsing.

**Root cause:** `str(None)` in Python returns the string `"None"`, not `None`. Common in router code doing `str(body.field) if body.field else None` when the field is optional.

**Fix — Use the field directly or explicit None check:**
```python
# ❌ Wrong — produces string "None"
order_id = str(body.order_id) if body.order_id else None  # body.order_id is None → str("None") = "None"

# ✅ Correct — pass None directly or use or operator
order_id = body.order_id or None  # stays None when body.order_id is None
# OR if you need to convert UUID to string:
order_id = str(body.order_id) if body.order_id is not None else None
```

**When this happens:** Any optional UUID/foreign key field in Pydantic schemas that gets passed through `str()` conversion. The `"None"` string will either crash UUID parsing or create invalid FK references.

### String status filter case sensitivity (not enums)
**Symptom:** `GET /api/v1/garage/records/?status=COMPLETED` returns `{\"total\": 0, \"items\": []}` despite records existing in the DB.

**Root cause:** String status columns (e.g., `status = String(20)`) are case-sensitive. A query like `.where(Model.status == \"COMPLETED\")` will NOT match DB rows with `status = \"completed\"`.

**Fix:** Use the exact case stored in the database:
```python
# Model stores lowercase strings
.where(ServiceRecord.status == \"completed\")  # ✅ matches
.where(ServiceRecord.status == \"COMPLETED\")  # ❌ zero results
```

**Frontend alignment:** When a template calls the API, ensure the status parameter matches:
```js
// ✅ Correct
await apiGet('/records/?status=completed');
// ❌ Wrong — returns zero results
await apiGet('/records/?status=COMPLETED');
```

**Quick diagnostic:** Query actual DB values to confirm case:
```sql
SELECT DISTINCT status FROM service_records;
-- Returns: completed, requested, pending (all lowercase)
```

## Template Editing Discipline

### `patch` stale-match loop on Jinja2 templates
**Symptom:** `patch` succeeds but removes the WRONG line (e.g. deletes `</div>`, then `<!-- comment -->`, then `<h2>`) because the `old_string` matched the button line in a different context position each time.

**Root cause:** After each successful `patch`, the file content shifts. The next `patch` with the SAME `old_string` now matches in a different position or matches adjacent context that has changed. Repeating identical `patch` calls on a template file destroys HTML structure.

**Rule — Maximum 2 `patch` attempts per template file:**
1. **First attempt:** `patch` with `old_string` that includes at least 2 lines of surrounding context
2. **If it fails or produces wrong output:** STOP patching. Use `read_file` to get the current file state, then either:
   - Issue a SINGLE `patch` with `old_string` taken from the ACTUAL current content, OR
   - Use `write_file` to rewrite the entire file (safe for template edits)
3. **Never loop on `patch`** — each successful patch changes the file, invalidating all subsequent `old_string` matches

**After editing:** Always rebuild Docker — `docker compose build --no-cache api` followed by `docker compose up -d api`. `docker compose restart` does NOT pick up template changes (the image is baked).

### `grep` returns no matches — the text is already gone
When `grep -n 'btn-order' file` returns exit code 1 (no matches), the text is already removed. The container may still serve old content — verify by rebuilding Docker, not by re-reading the file.

## Jinja2 + JavaScript Pitfalls (CRITICAL)

### `[object Object]` error display in form handlers

**Symptom:** After form submission (signin, signup, OTP), the error message displays `[object Object]` instead of the actual validation error.

**Root cause:** Pydantic v2 returns validation errors as `detail: [{loc: [...], msg: "..."}]` — an array of objects. JS `data.detail || 'msg'` stringifies to `[object Object]`.

**Fix — handle both array and string formats in ALL form handlers:**
```js
// In signin.html, signup.html, OTP forms, any inline form
if (Array.isArray(data.detail)) {
    message.textContent = data.detail.map(e => e.msg || e).join('; ');
} else {
    message.textContent = (typeof data.detail === 'string') ? data.detail : 'error';
}
```

Apply to: `signin.html`, `signup.html`, any inline form that reads `data.detail` from API responses.

### `res.json()` before `res.ok` — "Network error" on validation failures

**Symptom:** Signup/registration page shows "Network error. Please try again." when the API returns 422/500. Backend endpoint works fine in curl (200 OK with proper JSON).

**Root cause:** `const data = await res.json();` is called BEFORE checking `if (res.ok)`. When the API returns 422/500 with an error body, `res.json()` may parse successfully but the error handling block that checks `data.detail` never executes because the `if (res.ok)` branch runs instead, or the catch-all catches a serialization error from an HTML error response.

**Fix — Always check `res.ok` FIRST before parsing:**
```js
try {
    const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, first_name, last_name }),
    });
    if (!res.ok) {
        // Handle error BEFORE parsing JSON
        try {
            const data = await res.json();
            if (Array.isArray(data.detail)) {
                message.textContent = data.detail.map(e => e.msg || e).join('; ');
            } else {
                message.textContent = (typeof data.detail === 'string') ? data.detail : 'Registration failed';
            }
        } catch {
            message.textContent = 'Registration failed (status ' + res.status + ')';
        }
        message.className = 'auth-message error';
        btn.disabled = false;
        btn.textContent = 'Create Account';
        return;  // Important: exit early, don't continue to success path
    }
    // Only parse success response here
    const data = await res.json();
    message.textContent = 'Account created! Redirecting...';
    message.className = 'auth-message success';
    btn.disabled = false;
    setTimeout(() => window.location.href = '/signin', 1500);
} catch (err) {
    console.error('Signup error:', err);
    message.textContent = 'Network error. Please try again.';
    btn.disabled = false;
    btn.textContent = 'Create Account';
}
```

**Key rules:**
1. Check `if (!res.ok)` immediately after `await fetch()`, BEFORE any `res.json()`
2. Use `return` after error handling to prevent fallthrough to success path
3. Add `console.error(err)` in the catch block for debugging — "Network error" with no console output makes debugging impossible
4. Always reset button state (`btn.disabled = false; btn.textContent = ...`) in BOTH success and error paths

### Parent `display:none` CSS trap (vehicle detail page)

**Symptom:** Clicking "Book Test Drive", "Configure", "Order Now" — the action section never appears.

**Root cause:** `#orderSection` parent div has `style="display:none"`. Child sections (`#test-drive-section`, `#configurator-section`, `#finance-section`, `#trade-in-section`) are toggled to `display:block` but the parent still hides them.

**Fix:** Button handlers must show parent first: `document.getElementById('orderSection').style.display = 'block';` before toggling the child section.

### Password `min_length=8` in Pydantic auth schemas

**Root cause:** `LoginRequest` and `UserCreate` schemas enforce `min_length=8` on password fields. Test passwords like `pass123` (7 chars) are rejected with validation errors before bcrypt comparison ever runs. Use `password123` or `Pass123456!` for test credentials.

### Jinja2 consumes `${}` and backticks in inline `<script>`

**Symptom:** Inline `<script>` in Jinja2 templates produces `"Unexpected string"` or `"Invalid or unexpected token"` JS syntax errors in browser console. Page fetches return `401` or throw `TypeError: Failed to fetch`.

**Root cause:** Jinja2 treats `${...}` as variable interpolation syntax and backticks `` ` `` as special delimiters. When a template contains:
```js
// ❌ BROKEN — Jinja2 consumes ${token} and strips backticks
headers: { 'Authorization': `Bearer ${token}` },
```
The rendered HTML becomes:
```js
headers: { 'Authorization': 'Bearer ' }  // ${token} stripped!
```
Similarly, `` `...` `` template literals get escaped to `\`` in the rendered output, producing `SyntaxError`.

**Fix — Use string concatenation, NEVER template literals in inline `<script>`:**
```js
// ✅ Correct — plain string concatenation
const BASE_PATH = '{{ base_path }}';
var url = BASE_PATH + '/api/admin/customers?page=' + p;
var res = await fetch(url, {
    headers: { 'Authorization': 'Bearer ' + token }
});
```

**Rule:** All inline `<script>` in Jinja2 templates MUST use `var` declarations, `+` string concatenation, and standard JS functions. Never use:
- `` `template ${literal}` `` → use `'string' + var`
- `const`/`let` with `${}` → use `var` and `+`
- Arrow functions with template params → use `function(x)` and concatenation

### Use `data-href` for row click handlers, NOT inline `onclick`

When dynamically generating table rows, avoid inline `onclick="location.href='...'"` which breaks with nested quotes. Instead:
```js
rows += '<tr data-href="' + BASE_PATH + '/detail/' + c.id + '">';
// After building tbody, attach delegated handler:
tbody.addEventListener('click', function(e) {
    var tr = e.target.closest('tr');
    if (tr && tr.dataset.href) window.location.href = tr.dataset.href;
});
```

## Jinja2 Patterns

### Template inheritance
Always extend `base.html`:
```html
{% extends "base.html" %}
{% block title %}Page Title{% endblock %}
{% block content %}...{% endblock %}
```

### SQLite stores naive datetimes — never compare with `datetime.now(timezone.utc)`

**Symptom:** `TypeError: can't compare offset-naive and offset-aware datetimes` in endpoint code that checks expiration or compares stored datetime columns.

**Root cause:** SQLAlchemy stores `DateTime(timezone=True)` columns as naive strings in SQLite (SQLite has no timezone support). Pydantic `isoformat()` produces strings like `'2026-06-22 08:49:06.867913'` — no `+00:00` suffix. When read back, the column value is naive, but `datetime.now(timezone.utc)` is aware. Comparing them crashes.

**Fix — Always strip tzinfo before comparison:**
```python
from datetime import datetime, timezone

@router.post("/{id}/accept")
async def accept_offer(trade_in_id: int, db: AsyncSession = Depends(get_db)):
    # ... fetch trade_in ...
    if trade_in.offer_expires_at:
        expires = trade_in.offer_expires_at
        if expires.tzinfo is not None:
            expires = expires.replace(tzinfo=None)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if expires < now_naive:
            raise HTTPException(status_code=400, detail="Offer expired")
```

**When this happens:** Any endpoint that checks date boundaries (expiration, scheduled time, availability) on SQLite-backed models with `DateTime(timezone=True)` columns. Works fine on PostgreSQL, crashes on SQLite — a common trap when developing locally with SQLite.

### Starlette 1.3.1 + Jinja2 3.1.6 incompatibility (CRITICAL)
**Symptom:** `TypeError: unhashable type: 'dict'` in Jinja2 cache when rendering templates that use `{% extends "base.html" %}`. The error appears in container logs as:
```
File "/jinja2/utils.py", line 515, in __getitem__
    rv = self._mapping[key]
TypeError: unhashable type: 'dict'
```

**Root cause:** Starlette 1.3.1's `Jinja2Templates` wrapper passes a dict as the cache key when templates use inheritance. Jinja2 3.1.6's LRU cache rejects unhashable dict keys.

**Fix — Bypass `Jinja2Templates` and use raw Jinja2 `Environment` with `HTMLResponse`:**
```python
from starlette.templating import Jinja2Templates
from starlette.responses import HTMLResponse
import os

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/")
async def index(request: Request):
    return HTMLResponse(
        content=templates.get_template("index.html").render(
            request=request, app_name=settings.APP_NAME
        )
    )
```

**Do NOT use:** `fastapi.templating.Jinja2Templates.TemplateResponse()` — it triggers the bug.

**Alternative fix:** Pin `starlette>=1.4.0` or `jinja2>=3.1.7` (bug fixed upstream). Or pin `jinja2>=3.1.0,<3.1.4` as a temporary workaround.

**See also:** `references/starlette-jinja2-incompatibility.md` for full debugging notes.

### Admin sub-app authentication
For admin apps, use **server sessions** (starlette SessionMiddleware) instead of JWT for web UI.
- Sessions use cookies that browsers automatically include in all requests
- Page redirects work naturally without manual token management
- **When behind nginx reverse proxy:** Use `proxy_redirect / /admin/;` in nginx and `{{ base_path }}` in all template links. Do NOT set `root_path="/admin"` on FastAPI — it conflicts with `proxy_redirect` and causes double-prefixing (`/admin/admin/dashboard`). See `references/admin-sub-app-pattern.md` for complete nginx proxy pattern and `references/admin-logging-and-audit.md` for logging/audit setup.

**NEVER set `cookie_path` on SessionMiddleware behind nginx.** Setting `cookie_path="/admin/"` causes Starlette to reject cookies because the app sees stripped paths (`/dashboard` not `/admin/dashboard`), making the session unreadable. Always leave `cookie_path` at the default (`/`).

**Error handlers in inline JS must NOT redirect.** If a `fetch()` in `loadSummary()` or similar fails and the catch block redirects to `/login`, you create an infinite loop: dashboard → fetch error → redirect to `/login` → login sees session → redirect to `/dashboard` → repeat. Fix: log the error but do NOT redirect in the catch.
```js
// ❌ Wrong — creates redirect loop
} catch (ex) {
    console.error('Dashboard error:', ex);
    window.location.href = BASE_PATH + '/login';  // NEVER do this
}

// ✅ Correct — log only, let user click Logout if needed
} catch (ex) {
    console.error('Dashboard error:', ex);
}
```

**Session cookie → sessionStorage token bridge (direct URL access).** When a user accesses a protected page directly (typing URL or opening new tab), the session cookie is set but `sessionStorage` has no JWT token. If JS checks `!token` and redirects to `/login`, you get a loop: session validates → redirect to `/dashboard` → no token → redirect to `/login` → repeat.

**Fix — Add `/auth/token` endpoint that returns JWT from session:**
```python
@router.get("/token")
async def admin_token_from_session(request: Request):
    """Return a fresh JWT based on the session cookie."""
    user_id = request.session.get("admin_user_id")
    if not user_id:
        raise HTTPException(status_code=401)
    settings = get_settings()
    access_token = generate_access_token(user_id)
    return {"access_token": access_token, "token_type": "bearer"}
```

**Fix — Auto-populate token in `base.html` before any page script:**
```html
<!-- In base.html, before {% block scripts %} -->
<script>
(function ensureToken() {
    var token = sessionStorage.getItem('admin_access_token');
    if (!token && document.cookie.indexOf('session=') !== -1) {
        fetch('{{ base_path }}/api/admin/auth/token')
            .then(function(r) { if (r.ok) return r.json(); })
            .then(function(d) { if (d) sessionStorage.setItem('admin_access_token', d.access_token); })
            .catch(function() {});
    }
})();
</script>
```

**Fix — In page scripts, fetch token instead of redirecting:**
```js
// In dashboard.html loadSummary()
if (!token) {
    var tokenRes = await fetch(BASE_PATH + '/api/admin/auth/token');
    if (tokenRes.ok) {
        var tokenData = await tokenRes.json();
        token = tokenData.access_token;
        sessionStorage.setItem('admin_access_token', token);
    }
}
```

**Fix — Remove redirect-to-login on 401 in list pages.** The session cookie already proves auth — never redirect to `/login` on fetch errors when a session exists:
```js
// ❌ Wrong — creates loop when session is valid
if (res.status === 401) { window.location.href = BASE_PATH + '/login'; }
// ✅ Correct — log and return; session keeps user authenticated
if (!res.ok) { console.error('Fetch error:', res.status); return; }
```

**See also:** `references/admin-dashboard-stabilization.md` for full debugging notes.

**Make dashboard cards clickable** using `data-href` + delegated click handler:
```html
<div class="card bg-primary clickable" data-href="{{ base_path }}/customers">
```
```js
document.querySelectorAll('.clickable').forEach(function(card) {
    card.style.cursor = 'pointer';
    card.addEventListener('click', function() {
        window.location.href = this.dataset.href;
    });
});
```

### Bootstrap CDN link: do NOT use `{{ base_path }}/npm/` path
**Symptom:** Admin templates show unstyled, bare-bones layout. Console shows `404` on `/admin/npm/bootstrap@5.3.0/...`.

**Root cause:** `{{ base_path }}/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css` produces `/admin/npm/bootstrap...` but nginx has no proxy rule for `/npm/` — it's a CDN path, not an API route. Also, a common quote bug: `href="{{ base_path }}"/npm/..."` (note the `"` after `}}`) breaks the href entirely.

**Fix — use direct CDN URL:**
```html
<!-- ✅ Correct — loads from CDN -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<!-- ❌ Wrong — hits nginx with no matching proxy route -->
<link href="{{ base_path }}/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
```

### Jinja2 `{% block head %}` CSS cascade pitfall
Inline `<style>` blocks in `{% block head %}` render **before** the `<link rel=\"stylesheet\">` tag in `base.html`. The external stylesheet therefore **overrides** the inline styles due to CSS cascade order.

**Fix:** Move page-level wrapper styles (`.garage-page`, padding, margins) into the shared `style.css` alongside `.orders` and `.bookings`. The external stylesheet always wins over inline `<style>` in `{% block head %}`.

**Rule:** Page-level layout styles belong in `style.css`, not in template `<style>` blocks. Only keep truly feature-specific CSS (tabs, star rating, gallery grid) inline.

## CSS Patterns

### Shared vs Page-Specific
- Shared styles go in `static/css/style.css` (cards, buttons, forms, badges, layouts)
- Page-specific styles go in `static/css/<feature>.css` (tabs, ratings, galleries)
- Always check `style.css` first before writing new CSS — most patterns already exist

### Vehicle image display
When vehicles have `image_url` pointing to static files:
```html
<div class=\"vehicle-img\" style=\"background-image: url('/static/vehicles/{{ vehicle.image_url }}')\"></div>
```
**CSS pitfall:** Never use `background: var(--bg-secondary)` (shorthand overrides `background-image`). Use `background-color: var(--bg-secondary)` instead.

**Seed-time fix:** When `vehicle.image_url` is `NULL`, templates show gradient fallback. Ensure seed script sets `image_url` during vehicle creation from an image map, not just in the `vehicle_images` child table:
```python
for idx, row in enumerate(vehicle_data):
    img_path = IMAGE_MAP[idx] if idx < len(IMAGE_MAP) else None
    v = Vehicle(..., image_url=img_path, ...)
```

**JS-side fallback:** When rendering via JavaScript (not Jinja2), check for `null` before using:
```js
const thumb = v.image_url ? v.image_url : null;
const bg = thumb
    ? `background-image: url('${thumb}'); background-size: cover; background-position: center;`
    : `background: linear-gradient(135deg, #e63946, #f4a261);`;
```

## Dashboard Integration

See `references/dashboard-integration.md` for the complete pattern.

**Key principles:**
- Use `fetchJSON` helper with Bearer token auth
- Use `Promise.allSettled()` so one failing endpoint doesn't break the whole dashboard
- Handle both array `[]` and `{items: []}` response formats
- Membership card shows tier, points, progress bar with error fallback

## Deployment Workflow

### Container rebuild
```bash
cd /path/to/project/mvp_output && docker compose up -d --build api
```

### Template-only hotfix (no rebuild needed)
```bash
docker cp host/path/template.html mvp_output-api-1:/app/app/templates/template.html
```

**Rule:** For template-only changes, use `docker cp` for instant hotfix. For Python/JS/CSS changes, use `docker compose build && docker compose up -d api`.

### IMPORTANT: `execute_code` sandbox cannot reach Docker
The `execute_code` Python sandbox runs in `/tmp/` and **cannot call `subprocess.run(["docker", ...])`** — it returns empty results. For Docker-dependent operations:

1. **Prefer `terminal`** — run `docker compose exec` or `docker cp` directly via `terminal()`
2. **For data-heavy scripts:** Write the Python script to the project directory, then run via `terminal("python3 path/to/script.py")`
3. **For DB schema extraction:** Dump data to temp files via `terminal("docker compose exec postgres psql ... > /tmp/file.txt")`, then read those files in `execute_code`

### DB Migration Patterns

### Direct SQL for quick fixes
When Alembic is not set up or you need a quick column addition:
```bash
docker exec mvp_output-postgres-1 psql -U gloryev -d gloryev_uat -c \"ALTER TABLE <table> ADD COLUMN <col> <type>;\"
```

### Column rename with FK migration (raw SQL)
When a model's FK column name changes (e.g., `user_id` → `customer_id`), the DB column must be renamed along with its index and FK constraint:
```bash
# Drop existing FK
docker exec -i mvp_output-postgres-1 psql -U gloryev -d gloryev_uat \
  -c "ALTER TABLE documents DROP CONSTRAINT documents_user_id_fkey;"

# Rename column
docker exec -i mvp_output-postgres-1 psql -U gloryev -d gloryev_uat \
  -c "ALTER TABLE documents RENAME COLUMN user_id TO customer_id;"

# Replace index
docker exec -i mvp_output-postgres-1 psql -U gloryev -d gloryev_uat \
  -c "DROP INDEX IF EXISTS ix_documents_user_id;"
docker exec -i mvp_output-postgres-1 psql -U gloryev -d gloryev_uat \
  -c "CREATE INDEX ix_documents_customer_id ON documents(customer_id);"

# Add new FK
docker exec -i mvp_output-postgres-1 psql -U gloryev -d gloryev_uat \
  -c "ALTER TABLE documents ADD CONSTRAINT documents_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES customers(id);"

# Migrate data (if old FK pointed to users table)
docker exec -i mvp_output-postgres-1 psql -U gloryev -d gloryev_uat \
  -c "UPDATE documents d SET customer_id = u.customer_id FROM users u WHERE d.customer_id = u.id;"
```

### Alembic for proper migrations
When Alembic is available:
```bash
alembic revision --autogenerate -m \"add <col> to <table>\"
alembic upgrade head
```

## Verification Checklist

| Check | Method |
|---|---|
| API endpoint returns 200 | `curl -s -w \"%{http_code}\" http://localhost:8010/api/v1/<feature>/` |
| Template renders | Navigate to `/<feature>` in browser |
| Auth works | Log in as test user, verify scoped data |
| Tests pass | `pytest tests/test_<feature>.py -v` |
| Docker health | `docker compose ps` shows `healthy` |
| No 500 errors | `docker logs mvp_output-api-1 --tail 50 \| grep -i error` |

## Authentication & 401 Handling (Dual-Layer Pattern)

FastAPI + Jinja2 SSR requires BOTH server-side and client-side 401 handling because:
- **Direct navigation** (e.g. user types `/dashboard` in address bar) → handled by server-side exception handler
- **AJAX/fetch calls** (e.g. dashboard loads data via `fetch('/api/v1/orders')`) → handled by client-side `window.fetch` shadow

### Server-Side: Global 401 Exception Handler

Add to `main.py` (the FastAPI app):

```python
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        accept = request.headers.get('accept', '')
        if 'text/html' in accept or 'application/xhtml+xml' in accept:
            # Browser request — redirect to sign-in, preserving the original path
            next_url = request.url.path
            return RedirectResponse(f'/signin?next={next_url}', status_code=302)
    # JSON API request — return 401 as-is
    return JSONResponse({'detail': str(exc.detail)}, status_code=exc.status_code)
```

### Client-Side: `window.fetch` Shadowing in `<head>`

**CRITICAL: Must be in `<head>` of `base.html`, NOT in the footer.** Page inline `<script>` tags execute before the footer loads, so shadowing in the footer never intercepts their `fetch()` calls.

```html
<!-- In base.html, inside <head>, BEFORE </head> -->
<script>
(function() {
    var originalFetch = window.fetch;
    var handle401 = function() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user_name');
        var gs = document.querySelector('.auth-guest');
        var us = document.querySelector('.auth-user');
        var ge = document.getElementById('greeting');
        if (gs) gs.style.display = 'inline-flex';
        if (us) us.style.display = 'none';
        if (ge) ge.style.display = 'none';
        window.location.href = '/signin?next=' + encodeURIComponent(window.location.pathname);
    };
    window.fetch = function(url, options) {
        options = options || {};
        if (!options.headers) options.headers = {};
        // Convert URL/Request objects to string — .indexOf() doesn't exist on those types
        var urlStr = (url instanceof URL || url instanceof Request) ? url.toString() : String(url || '');
        // Auto-inject auth token for API endpoints
        if (urlStr.indexOf('/api/') === 0 && !options.headers['Authorization']) {
            var t = localStorage.getItem('access_token');
            if (t) options.headers['Authorization'] = 'Bearer ' + t;
        }
        return originalFetch(url, options).then(function(r) {
            if (r.status === 401 && urlStr.indexOf('/api/') === 0) {
                handle401();
                throw new Error('401 Unauthorized');
            }
            return r;
        });
    };
    window.apiFetch = window.fetch;  // Alias for explicit use
})();
</script>
```

### Per-Template Fallback (for non-fetch API calls)

Some templates use custom wrappers (`apiGet`, `apiPost`, `fetchJSON`) that may not go through the shadowed `window.fetch`. Add a `handleUnauthorized()` function in each template's inline script:

```javascript
function handleUnauthorized() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_name');
    window.location.href = '/signin?next=' + encodeURIComponent(window.location.pathname);
}
// In fetchJSON/apiGet/apiPost:
if (res.status === 401) { handleUnauthorized(); return; }
```

### Pitfalls

**Auth redirect infinite loop in admin templates.** When a template's JS redirects to `{{ base_path }}` (i.e. `/` or `/admin/`) on auth failure, and the root path returns `303 → /dashboard`, you get an infinite loop: `/` → 303 → `/dashboard` → JS runs → no token → redirect to `/` → repeat. The log fills with `GET / HTTP/1.1 303` and `GET /dashboard HTTP/1.1 200` at 10+ req/sec.

**Fix — redirect to `/login` instead of the root path in ALL admin templates:**
```javascript
// ❌ Wrong — creates redirect loop via 303
if (!token) { window.location.href = '{{ base_path }}'; return; }
// ✅ Correct — goes directly to login page
if (!token) { window.location.href = '{{ base_path }}/login'; return; }
```

Apply the same fix to auth-failure handlers (401 catches) in every template. Search pattern: `window.location.href = '{{ base_path }}';` should become `window.location.href = '{{ base_path }}/login';`

**SERVER-SIDE REDIRECT PATHS MUST BE BARE.** In `require_auth()` and login page handlers, use bare paths (`/`, `/dashboard`, `/login`) — NOT `ADMIN_ROOT_PATH`. The nginx `proxy_redirect / /admin/` rule rewrites bare paths. Using `ADMIN_ROOT_PATH` in server-side redirects causes double-prefixing (`/admin` → `/admin/admin`) and crashes through 404 loops. `ADMIN_ROOT_PATH` is ONLY for template `{{ base_path }}` in client-side links (JS `window.location.href`, `<a href>`, `<form action>`).

```python
# ❌ Wrong — double-prefixes through nginx
return RedirectResponse(url=ADMIN_ROOT_PATH)  # sends /admin, nginx rewrites to /admin/admin
# ✅ Correct — bare path, nginx adds the prefix
return RedirectResponse(url="/")
```

**EXPLICIT `/login` ROUTE NEEDED.** Admin templates reference `{{ base_path }}/login` for auth-failure redirects. Without an explicit route, this returns 404. Add to `main.py`:

```python
@app.get("/login", response_class=HTMLResponse)
async def page_login_alias(request: Request):
    ctx = get_template_context(request)
    return template_response("login.html", ctx)
```

**DUAL AUTH SERVICES — changes must go in BOTH files.** The project has TWO auth service implementations: `app/services/auth_service.py` and `app/utils/mock_auth.py`. **The routers import `mock_auth_service` from `app.utils`, NOT `auth_service`.** Any fix to `get_user_profile`, `register_user`, or other auth methods must be applied to BOTH files, otherwise the runtime change has zero effect. See `references/dual-auth-service-pitfall.md`.

**`window.fetch` shadowing in `<footer>` does NOT work.** Page scripts that use `<script>` tags in the `<body>` execute before the footer IIFE runs. The fetch shadow must be in `<head>` so it's installed before ANY page script executes.

**`url.indexOf()` crashes on `URL`/`Request` objects.** Pages like `care.html` use `new URL('/api/v1/care/faqs')` which passes a `URL` object — that type has no `.indexOf()` method. Always convert to string first: `var urlStr = (url instanceof URL || url instanceof Request) ? url.toString() : String(url || '');` then check `urlStr.indexOf('/api/')`.

**Docker `COPY . .` means template changes require full rebuild.** A `docker compose restart` does NOT pick up changed template files — the image was baked with the old version. Use `docker cp` for instant template hotfixes or `docker compose build && docker compose up -d api` for permanent changes.

**Shadowed `window.fetch` returns a Promise that throws on 401.** Calling code must either:
- Use `.catch()` to handle the thrown Error, OR
- Let it propagate (the redirect has already happened in `handle401()`)

### Verification

1. Unauthenticated → visit `/dashboard` → should redirect to `/signin?next=/dashboard`
2. Signed in → let token expire → trigger any API call → should redirect to `/signin?next=...`
3. No raw "Error: API 401" messages should appear on any page
4. **Check for redirect loops:** Run `docker exec <container> grep -rn "window.location.href = '{{ base_path }}';" /app/app/admin/templates/` — any matches that redirect to root instead of `/login` will cause infinite refresh loops

## Reference Files

### Templates (copy and modify)
- `templates/uvicorn_logging.json` — Uvicorn log config with RotatingFileHandler (file + stdout, propagate:false)

This skill has extensive reference files for specific patterns and debugging scenarios:

- `references/invoice-serialization-debugging.md` — PydanticSerializationError debugging: schema-model field mismatch (user_id vs customer_id), enum type mismatch, raw ORM objects in router returns, ORM objects in service dict returns
- `references/admin-dashboard-pagination-debug.md` — Admin dashboard pagination debugging: non-deterministic ordering, with_only_columns() mutation, model-attribute mismatches, enum-to-string comparison, empty-string date rejection
- `references/admin-sub-app-pattern.md` — Separate admin app within existing FastAPI project (structure, Docker, auth, PII redaction, transition validation, nginx proxy)
- `references/admin-dashboard-stabilization.md` — Admin dashboard stabilization: auth redirect loop, server-side redirect double-prefixing, Bootstrap CDN link, /login route, session token bridging
- `references/admin-detail-pages.md` — Admin detail pages: template string concatenation, selectinload for relationships, enum serialization
- `references/admin-logging-and-audit.md` — Structured logging setup, PII redaction wiring, request logging middleware, audit trail model/service, error handler logging
- `references/otel-tracing-setup.md` — OpenTelemetry instrumentation, in-memory exporter, try/except wiring, admin import pitfalls
- `references/observability-status-review.md` — Spec-to-implementation gap analysis checklist: verifying metrics collection, OTel enablement, audit wiring, and common anti-patterns (dead metrics, commented-out instrumentation, partial audit trails)
- `references/p1-backlog-fix-pattern.md` — P1 backlog audit patterns: read-only vs mutation service verification, OTel/metrics already-done checklist, frontend-backend URL mismatch detection, cart scaffolding pattern, subagent delegation limitations

- `references/dashboard-integration.md` — Dashboard cards, live API counts, membership card
- `references/customer-scoped-data-pattern.md` — User→Customer resolution, auth dependencies
- `references/orm-fk-mismatch-debugging.md` — Diagnosing FK attribute errors
- `references/customer-model-refactoring.md` — Migrating from User to Customer architecture
- `references/feature-build-pitfalls.md` — Common mistakes and fixes
- `references/hire-feature-build.md` — Car hiring/subscription feature pattern
- `references/car-hiring-patterns.md` — CarBar.com.au UX patterns adapted for this app
- `references/payment-enriched-endpoint-debugging.md` — Payment flow debugging
- `references/frontend_payment_patterns.md` — Payment page JS patterns
- `references/hiring-vehicle-list-ui.md` — Hireable vehicle filtering and display
- `references/hire-payment-flow.md` — Hire→Payment→Redirect flow
- `references/hire-page-vehicle-images.md` — Vehicle image display in hiring
- `references/auth-aware-nav-header.md` — Navigation with auth state
- `references/nav-greeting-feature.md` — Personalized greeting in nav
- `references/browsing-filter-fixes.md` — Vehicle browsing filter fixes
- `references/configurator-empty-trims.md` — Configurator empty state handling
- `references/garage-service-debugging.md` — Garage service debugging
- `references/garage-service-smoke-test.md` — Garage service smoke testing
- `references/garage-service-module.md` — Garage service module structure
- `references/garage-service-enum-fix.md` — Service record enum fixes
- `references/service-syntax-debugging.md` — Service record syntax debugging
- `references/garage-styling-standardization.md` — Garage page styling
- `references/membership-feature-build.md` — Membership feature pattern
- `references/membership-enum-casing-bug.md` — Membership enum casing issues
- `references/hire-feature-build.md` — Hire feature build process
- `references/hiring-feature-build.md` — Hiring feature implementation
- `references/payment-enriched-endpoint-debugging.md` — Payment endpoint debugging
- `references/hire-payment-flow.md` — Hire payment flow
- `references/hiring-vehicle-list-ui.md` — Hireable vehicle list UI
- `references/hire-page-vehicle-images.md` — Hire page vehicle images
- `references/order-checkout-triple-failure.md` — Order checkout fixes
- `references/care-module-fk-debugging.md` — Care module FK issues
- `references/care-inline-messages.md` — Care inline messaging
- `references/care-page-styling.md` — Care page styling
- `references/auth-aware-nav-header.md` — Auth-aware navigation
- `references/nav-greeting-feature.md` — Nav greeting feature
- `references/membership-feature-build.md` — Membership feature build
- `references/customer-model-refactoring.md` — Customer model refactoring
- `references/sqlalchemy-uuid-string-mismatch.md` — UUID string comparison issues
- `references/fastapi-route-shadowing.md` — FastAPI route shadowing fixes (literal before parameterized)
- `references/docker-cp-rebuild-loss.md` — Docker build wipes docker cp changes; __init__.py export mismatch causes ImportError
- `references/mock-auth-debugging.md` — Mock auth debugging patterns
- `references/global-401-handling.md` — Dual-layer 401 handling (server + client), head vs footer pitfall
- `references/depends-none-kw-422.md` — Depends(None) keyword 422 errors
- `references/feature-build-pitfalls.md` — Feature build pitfalls
- `references/feedback-serialization-fix.md` — Feedback feature: serialization, schema mismatch, status case fix
- `references/owned-entities-dropdown.md` — Owned entities dropdown with identifiers (plate numbers, serial numbers)
- `references/db-schema-discovery.md` — DB schema discovery patterns
- `references/db-schema-documentation.md` — Full schema documentation generation (columns, constraints, enums, indexes → markdown)
- `references/css-visibility-toggle.md` — CSS visibility toggling
- `references/evgroup-image-extraction.md` — EV group image extraction
- `references/pil-car-color-extraction.md` — PIL car color extraction
- `references/enum-creation-pattern.md` — Enum creation patterns
- `references/jwt-atomic-session-testing.md` — JWT session testing
- `references/garage-service-session-log.md` — Garage service session log
- `references/service-syntax-debugging.md` — Service syntax debugging
- `references/garage-service-debugging.md` — Garage service debugging
