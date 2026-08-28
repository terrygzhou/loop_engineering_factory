---
name: incremental-implementation
description: >
  Implement features as thin vertical slices — one task at a time,
  each fully working and verified before moving to the next. Prevents
  large untested codebases and partial features. Optimized for FastAPI
  routes, Pydantic models, Jinja2 templates, and Docker services.
version: 1.0.0
author: hermes
triggers:
  - "implement"
  - "build the feature"
  - "start coding"
  - "let's build"
  - "implement incrementally"
  - "thin slice"
  - "vertical slice"
  - "step by step implementation"
tools:
  - read_file
  - write_file
  - search_files
  - patch
  - terminal
---

# incremental-implementation

## Purpose

Break a feature into the smallest possible vertical slices — each slice
touches all layers (API, logic, data, template) and is independently
testable. Implement one slice at a time, verify it works, then move to
the next. This produces working software continuously instead of a
large batch of untested code.

## Process

### 1. Decompose the feature into vertical slices

A vertical slice goes through all layers:

```
Slice 1: Minimal happy path
  - API endpoint (POST /api/v1/items)
  - Pydantic request model
  - Database insert
  - JSON response

Slice 2: Read back what was created
  - API endpoint (GET /api/v1/items/{id})
  - Pydantic response model
  - Database query
  - 404 handling

Slice 3: List with pagination
  - API endpoint (GET /api/v1/items)
  - Query params (page, per_page)
  - Paginated response

Slice 4: Update an item
  - API endpoint (PATCH /api/v1/items/{id})
  - Partial update logic
  - Conflict handling

Slice 5: Jinja2 template for admin view
  - Route returning HTML
  - Template with list rendering
  - Error display
```

**Rule:** Each slice must be demonstrably working before the next
begins. "Working" means: code written, tests passing (or manual
verification done), and the behavior matches the spec.

### 2. Implement one slice at a time

For each slice:

a. **Write the minimum code** — no extra features, no future-proofing.
b. **Write or run the test** — unit test, integration test, or manual
   curl request against the running server.
c. **Verify it works** — the output matches expectations.
d. **Commit** — with a clear message referencing the slice.

### 3. Verify before proceeding

After each slice, confirm:

- [ ] The endpoint/template returns the expected response
- [ ] Error cases for this slice are handled (e.g., 404, 422)
- [ ] No regressions in previously working slices
- [ ] Docker container still builds and runs cleanly

If verification fails, fix the current slice before moving forward.
Do not "fix it in the next slice."

### 4. Handle interdependencies

When slices depend on each other:

- Implement stubs for unimplemented dependencies (return mock data)
- Replace stubs with real implementations as their slices complete
- Never leave a stub past the end of the next slice

Example: Slice 1 (create) might stub the "get by ID" call until
Slice 2 implements it.

### 5. Iterate with user feedback

After completing 2–3 slices, show the user what's working:

*"I've implemented create, read, and list endpoints. They're all
returning valid responses. Ready for you to test before I continue
with update and delete."*

This catches misalignment early — before you've built half the
feature incorrectly.

## Template: Slice Implementation

For each slice, follow this structure:

1. **Define the contract** — What HTTP method, path, request body,
   response body.
2. **Add the Pydantic model(s)** — Request and response schemas.
3. **Implement the route** — Minimal handler logic.
4. **Wire the data layer** — Database call or stub.
5. **Test** — Run the endpoint and verify the response.

Example for Slice 1 (Create Item):

```python
# models/item.py
from pydantic import BaseModel, Field


class CreateItemRequest(BaseModel):
    name: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=0)


class ItemResponse(BaseModel):
    id: int
    name: str
    quantity: int


# routes/items.py
from fastapi import APIRouter
from .models.item import CreateItemRequest, ItemResponse

router = APIRouter(prefix="/api/v1/items")


@router.post("", response_model=ItemResponse, status_code=201)
async def create_item(body: CreateItemRequest):
    # TODO: persist to database
    return ItemResponse(id=1, name=body.name, quantity=body.quantity)
```

## Pitfalls

- **Don't build horizontally.** A horizontal layer (e.g., "finish all
  models first, then all routes") produces nothing that works until
  the very end. Vertical slices work from the start.
- **Don't skip error handling in a slice.** Even a minimal slice should
  handle its primary error case (e.g., 404 on GET).
- **Don't "future-proof" a slice.** If pagination isn't needed for the
  current slice, don't add it. Add it when the slice calls for it.
- **Don't accumulate technical debt between slices.** Each slice should
  leave the codebase in a clean state. Fix linting, formatting, or
  type errors in the same slice that introduces them.
- **Don't make slices too large.** If a slice takes more than 20
  minutes to implement and verify, it's too big — split it further.

## Verification

- Each slice has a corresponding test or manual verification record.
- The Docker container builds and runs after each slice.
- All previous slices still work (no regressions).
- The user has confirmed direction after 2–3 slices.
- Total implementation time is within expected bounds.
