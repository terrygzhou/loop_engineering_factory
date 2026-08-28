---
name: api-and-interface-design
description: >
  Contract-first API and interface design. Define types, schemas, and
  boundary validation before implementation. Covers REST API design,
  Pydantic models, request/response contracts, and Hyrum's Law
  awareness. Optimized for FastAPI + Jinja2 + Docker stacks.
version: 1.0.0
author: hermes
triggers:
  - "design the API"
  - "API design"
  - "interface design"
  - "contract first"
  - "define the schema"
  - "API contract"
  - "Pydantic model"
  - "request response"
  - "endpoint design"
tools:
  - read_file
  - write_file
  - search_files
  - patch
---

# api-and-interface-design

## Purpose

Define clear, versioned contracts for all API surfaces before writing
implementation code. This ensures type safety, documentation
generation (OpenAPI/Swagger), and predictable error handling across the
FastAPI stack.

## Process

### 1. Enumerate all API surfaces

List every external and internal interface:

- REST endpoints (GET, POST, PUT, PATCH, DELETE)
- WebSocket endpoints
- Background task triggers
- Internal service-to-service calls
- CLI commands
- Jinja2 template data contracts (what context dict keys are passed)

### 2. Define Pydantic models for each surface

For each endpoint, create:

- **Request model** — Fields with types, validators, defaults, and
  descriptions. Use `Field(...)` for schema documentation.
- **Response model** — Fields the client can depend on. Be explicit
  about optional vs. required.
- **Error model** — Standardized error responses with error code,
  message, and details.

Example structure:

```python
from pydantic import BaseModel, Field
from enum import Enum


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class CreateItemRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=5000)
    quantity: int = Field(..., ge=0)
    sort_by: SortOrder = Field(default=SortOrder.ASC)


class ItemResponse(BaseModel):
    id: int
    name: str
    description: str
    quantity: int
    created_at: datetime
    updated_at: datetime
```

### 3. Design endpoint paths and methods

Follow REST conventions:

- Use nouns for resources (`/api/v1/items`, not `/api/v1/getItems`)
- Use HTTP methods semantically (GET for read, POST for create, PUT
  for replace, PATCH for update, DELETE for remove)
- Version APIs in the path (`/api/v1/`)
- Use query params for filtering/sorting/pagination, not path segments

### 4. Define error contracts

Standardize error responses across all endpoints:

```python
class ErrorResponse(BaseModel):
    error_code: str  # e.g., "VALIDATION_ERROR", "NOT_FOUND"
    message: str  # Human-readable
    details: dict = {}  # Field-level validation errors, etc.
    request_id: str  # Correlation ID for debugging
```

Map HTTP status codes consistently:

- 200/201 — Success
- 400 — Validation error
- 401 — Unauthorized
- 403 — Forbidden
- 404 — Not found
- 409 — Conflict (duplicate, state violation)
- 422 — Unprocessable entity (Pydantic validation)
- 500 — Internal server error

### 5. Document with OpenAPI/Swagger

FastAPI generates OpenAPI automatically from Pydantic models and
decorators. Add:

- `summary` and `description` on every route
- `response_model` parameter
- `status_code` for non-200 responses
- `deprecated` flags for sunset endpoints

### 6. Apply Hyrum's Law awareness

*Hyrum's Law*: "With a sufficient number of users of an API, it doesn't
matter what you promise in the contract — all observable behaviors of
your system will be depended on by someone."

Practical implications:

- **Don't change response shapes** without versioning or deprecation
  notices
- **Don't remove fields** from response models — mark as deprecated
  first
- **Don't change error message text** — clients may parse it
- **Document all observable behaviors** — HTTP headers, response times,
  rate limits, etc.
- **Add extra fields** freely (backward compatible), but never remove

### 7. Add boundary validation middleware

Implement a global exception handler that catches all unhandled errors
and returns the standardized `ErrorResponse`:

```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "request_id": str(request.headers.get("X-Request-ID", "")),
        },
    )
```

## Pitfalls

- **Don't skip the contract phase.** Jumping straight to implementation
  leads to inconsistent APIs and costly refactors.
- **Don't over-engineer the first version.** A minimal, correct API
  that can evolve is better than a perfect API that never ships.
- **Don't mix validation with business logic.** Pydantic models should
  handle shape and type validation; business rules belong in service
  layers.
- **Don't forget pagination contracts.** Every list endpoint must
  define `page`, `per_page`, and total count in the response.
- **Don't expose internal IDs** in public APIs unless necessary. Use
  UUIDs or opaque identifiers when possible.

## Verification

- All endpoints have documented request and response models.
- OpenAPI/Swagger docs are generated and accessible (`/docs`).
- Error responses follow the standardized contract.
- No nullable fields in response models without explicit documentation.
- Hyrum's Law checklist reviewed for each new endpoint.
- Global exception handler is registered and tested.
