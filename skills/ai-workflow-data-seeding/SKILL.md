---
name: ai-workflow-data-seeding
description: Database seeding for AI-driven development workflows (DEFINE → PLAN → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT)
---

# Data Seeding for AI-Driven Development Workflows

## Trigger

Any task involving database seeding in an AI loop engineering context. Also applies to migrating seed data between projects with different database schemas or ORM versions.

## What This Skill Covers

1. **Seed script creation** for SQLAlchemy 2.0 async models
2. **Workflow integration** of seeding as a distinct phase in AI-driven development loops
3. **Data migration** between different project structures while preserving business logic
4. **Idempotent seeding** patterns that work across workflow iterations

## Key Patterns

### SQLAlchemy 2.0 Async Seeding

```python
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_table(session: AsyncSession, table_cls, data: list[dict]):
    for row in data:
        stmt = insert(table_cls).values(**row)
        await session.execute(stmt)
    await session.commit()
```

### Idempotent Seeding

- Use `INSERT OR IGNORE` for SQLite: `db.dialect.supports_multivalues_insert = True`
- For UUID PKs: generate deterministic UUIDs based on content hash
- For INTEGER PKs: use sequence or explicit IDs with `ON CONFLICT DO NOTHING`

### Mixed Primary Key Types

- **INTEGER PKs**: `user`, `item`, `order`, `category`, `review`
- **UUID PKs**: `address`, `transaction`, `variant`, `image`, `tracking`, `refund`, `order_item`, `notification`, `wishlist`, `coupon`, `support_ticket`
- **FK relationships**: User (INT) → Address (UUID) → other UUID-based tables

### FK Cascade Seeding Order

Seed parent tables before children to satisfy FK constraints:

1. **Level 1 (no deps)**: `User`, `Category`
2. **Level 2 (depend on L1)**: `Item` (links to User), `Address` (links to User)
3. **Level 3 (depend on L2)**: `Order` (links to User), `Variant` (links to Item), `Image` (links to Item)
4. **Level 4 (depend on L3)**: `OrderItem` (links to Order + Variant), `Review` (links to User + Item)
5. **Level 5 (leaf)**: `Notification`, `SupportTicket`, `Coupon`, etc.

```python
# Example: deterministic UUID from content hash
import hashlib
import uuid


def deterministic_uuid(seed: str) -> uuid.UUID:
    """Generate a stable UUID from a seed string for idempotent seeding."""
    return uuid.UUID(hashlib.sha256(seed.encode()).hexdigest[:32])


# Usage in seed data
address_data = [
    {
        "id": deterministic_uuid("address:123-main-st"),
        "user_id": 1,
        "street": "123 Main St",
        "city": "Springfield",
    },
    {
        "id": deterministic_uuid("address:456-oak-ave"),
        "user_id": 2,
        "street": "456 Oak Ave",
        "city": "Portland",
    },
]
```

### Workflow Integration

Insert seeding as a phase between BUILD and VERIFY:

```
DEFINE → PLAN → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
```

The SEED_DATA node:

1. Generates/imports seed data
2. Executes against target database
3. Returns success/failure with row counts
4. Feeds into VERIFY for UAT against populated data

### Workflow State Integration

After seeding, update the workflow state so downstream nodes know what data exists:

```python
workflow_state["seed"] = {
    "status": "success",
    "tables": {
        "user": {"inserted": 10, "skipped": 0},
        "item": {"inserted": 20, "skipped": 0},
        "order": {"inserted": 15, "skipped": 0},
        "order_item": {"inserted": 40, "skipped": 0},
    },
    "total_rows": 85,
}
```

## Pitfalls

- **PG_UUID on SQLite**: SQLAlchemy's `PG_UUID(as_uuid=True)` creates `VARCHAR(36)` in SQLite — seed must provide string UUIDs, not Python UUID objects
- **Timezone handling**: `dt.replace(tzinfo=None)` required for SQLite naive datetime compatibility
- **Relationship cascade order**: Seed parent tables first (User → Item → others), respect FK constraints
- **Static assets**: Related media files (e.g. images) must be copied to the static assets directory before seeding references them
- **Workflow state**: Seed node must update workflow state with actual row counts for VERIFY to validate

## Verification

After seeding, VERIFY should confirm:

- Expected row counts per table
- FK constraints satisfied (no orphaned records)
- API endpoints return populated data (not empty lists)
- Frontend renders seeded data correctly