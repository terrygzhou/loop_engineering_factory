---
name: security-and-hardening
description: Security-first development practices — STRIDE threat modeling, input validation, authentication patterns, rate limiting, secret management
category: software-development
---

# Security and Hardening

## Purpose

Apply security practices during BUILD phase — input validation, authentication, authorization, rate limiting, secret management. Post-implementation aggregate pass.

## Security Checklist

### Authentication & Authorization
- API key or session-based auth for protected endpoints
- Role-based access control (RBAC) for admin functions
- Password hashing (bcrypt/scrypt) — never plain text
- Token expiration and refresh rotation
- CSRF tokens for state-changing HTTP methods

### Input Validation
- All user inputs validated at API boundary
- Type checking on all parameters
- String length limits to prevent buffer overflow
- SQL injection prevention (parameterized queries)
- XSS prevention (input encoding, output escaping)

### Rate Limiting
- API endpoints: 100 req/min per IP
- Auth endpoints: 10 req/min per IP
- File uploads: size limits + type whitelisting

### Secret Management
- No hardcoded credentials in code
- Environment variables loaded at runtime
- Secrets injected via platform secret manager in production
- .gitignore includes `.env` and credential files

### Data Protection
- HTTPS-only in production
- Sensitive data encrypted at rest
- PII minimization and retention policies
- SQL injection prevention via parameterized queries
- File uploads scanned and validated

## Implementation Pattern

```python
# Input validation
@validator("field_name")
def validate_field(cls, v):
    return v.strip()[:255]

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()

@app.post("/api/v1/resource")
@limiter.limit("100/minute")
async def create_resource(data: ResourceCreate):
    ...
```

## STRIDE Threat Model

| Threat | Mitigation |
|--------|-----------|
| Spoofing | Auth tokens, MFA for admin |
| Tampering | Input validation, checksums |
| Repudiation | Audit logs, non-repudiable actions |
| Info Disclosure | HTTPS, encryption, least privilege |
| Denial of Service | Rate limiting, circuit breakers |
| Elevation of Privilege | RBAC, input sanitization |

## Usage

Called as an aggregate pass after IMPLEMENT completion in BUILD subgraph. Scans the generated codebase for security patterns and gaps.

## Related Skills

- `requesting-code-review` — post-security review pass
- `docker-compose-deployment` — container security (least-privilege users, read-only FS)
- `production-deployment` — cloud security (WAF, VPC, secrets management)