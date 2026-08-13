#!/usr/bin/env bash
# UAT Pipeline — automated workflow execution, bug tracking, and fix dispatch
# Run via cron every 2 hours: 0 */2 * * *
# Usage: ./scripts/uat_pipeline.sh [OPTIONS]
#   --project NAME       Project name (default: My_test_CRM)
#   --description TEXT   Project description
#   --project-dir PATH   Output directory (default: ./mvp_output)
#   --container NAME     Docker container name (default: loop)
#   --webapp-url URL     Web app URL (default: http://localhost:8011)
#   --max-wait SECONDS   Max wait for workflow (default: 1200)
set -euo pipefail

# ── CLI argument parsing ─────────────────────────────────────────────
PROJECT="${PROJECT:-My_test_CRM}"
PROJECT_DESC="${PROJECT_DESC:-App for managing contacts/customers — contact details, emails, and meeting appointments synced with Google Calendar}"
PROJECT_DIR="${PROJECT_DIR:-./mvp_output}"
CONTAINER="${CONTAINER:-loop}"
WEBAPP_URL="${WEBAPP_URL:-http://localhost:8011}"
MAX_WAIT="${MAX_WAIT:-1200}"
UAT_PASS_RATE_THRESHOLD="${UAT_PASS_RATE_THRESHOLD:-0.95}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)     PROJECT="$2"; shift 2 ;;
    --description) PROJECT_DESC="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --container)   CONTAINER="$2"; shift 2 ;;
    --webapp-url)  WEBAPP_URL="$2"; shift 2 ;;
    --max-wait)    MAX_WAIT="$2"; shift 2 ;;
    --uat-threshold) UAT_PASS_RATE_THRESHOLD="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

LOG_DIR="${LOG_DIR:-logs}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/uat_pipeline_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "========================================"
log "UAT Pipeline started — $TIMESTAMP"
log "  Project: $PROJECT"
log "  Container: $CONTAINER"
log "  Web app: $WEBAPP_URL"
log "========================================"

# ── 1. Health Check ──────────────────────────────────────────────────
log "→ Health check: $CONTAINER container"
if ! docker ps --format '{{.Names}}' | grep -q "$CONTAINER"; then
  log "ERROR: $CONTAINER not running — skipping run"
  exit 1
fi

STATUS=$(curl -sf "$WEBAPP_URL/api/status" 2>/dev/null || echo "unreachable")
if [ -z "$STATUS" ]; then
  log "ERROR: /api/status unreachable — skipping run"
  exit 1
fi

CURRENT_PHASE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase','unknown'))" 2>/dev/null)
CURRENT_STATUS=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
log "Current state: status=$CURRENT_STATUS phase=$CURRENT_PHASE"

# ── 2. Start Workflow if Idle ────────────────────────────────────────
if [ "$CURRENT_STATUS" = "idle" ] || [ "$CURRENT_STATUS" = "complete" ]; then
  log "→ Workflow idle — starting new workflow"

  # Build project spec JSON from parameters
  PROJECT_SPEC=$(python3 -c "
import json
spec = {
    'project_name': '$PROJECT',
    'description': '''$PROJECT_DESC''',
    'features': [
        'Create, update contacts',
        'Receive emails and associate with contacts',
        'Make appointments with groups of contacts'
    ],
    'entities': {
        'Contact': ['Contact_ID', 'first_name', 'last_name', 'email', 'mobile', 'address', 'sex', 'date_of_birth', 'interests'],
        'Email': ['sent_by', 'contact_ID', 'receive_date', 'headline', 'content'],
        'Appointment': ['eventID', 'event_name', 'date', 'time', 'venue', 'online_link']
    },
    'apis': [
        'CRUD APIs for contacts',
        'CRUD APIs for emails per customer',
        'CRUD APIs for appointment booking to Google Calendar'
    ]
}
print(json.dumps(spec))
")

  START_RESPONSE=$(curl -sf -X POST "$WEBAPP_URL/api/start" \
    -H "Content-Type: application/json" \
    -d "$PROJECT_SPEC" 2>/dev/null || echo "failed")

  log "Start response: $START_RESPONSE"
  log "Waiting 10s for workflow to initialize..."
  sleep 10
fi

# ── 3. Monitor Execution ─────────────────────────────────────────────
log "→ Monitoring workflow execution..."
ELAPSED=0
POLL_INTERVAL=15
PHASE_LOG="$LOG_DIR/phase_log_${TIMESTAMP}.json"

while [ $ELAPSED -lt $MAX_WAIT ]; do
  STATUS=$(curl -sf "$WEBAPP_URL/api/status" 2>/dev/null || echo '{"status":"unknown"}')
  STATUS_VAL=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
  PHASE_VAL=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase','—'))" 2>/dev/null)
  CYCLE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cycle',0))" 2>/dev/null)

  log "  status=$STATUS_VAL phase=$PHASE_VAL cycle=$CYCLE (elapsed: ${ELAPSED}s)"

  if [ "$STATUS_VAL" = "complete" ]; then
    log "✓ Workflow completed successfully"
    break
  fi

  if [ "$STATUS_VAL" = "error" ] || [ "$STATUS_VAL" = "failed" ]; then
    log "✗ Workflow failed with status: $STATUS_VAL"
    break
  fi

  # Check for stuck phase (>300s in same phase) — portable date parsing via python3
  PHASE_STARTED=$(echo "$STATUS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
phases=d.get('phases',{})
for k,v in phases.items():
  if v.get('status')=='running':
    print(v.get('startedAt',''))
" 2>/dev/null)

  if [ -n "$PHASE_STARTED" ]; then
    STUCK_FLAG=$(python3 -c "
from datetime import datetime, timezone
import sys
try:
    ts = '$PHASE_STARTED'
    # Try ISO format parsing
    for fmt in '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z':
        try:
            started = datetime.strptime(ts, fmt)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            print('yes' if elapsed > 300 else 'no')
            sys.exit()
        except ValueError:
            continue
    print('no')
except Exception:
    print('no')
" 2>/dev/null)
    if [ "$STUCK_FLAG" = "yes" ]; then
      log "⚠ Phase $PHASE_VAL stuck for >300s — flagging"
    fi
  fi

  sleep $POLL_INTERVAL
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

# Save final status
echo "$STATUS" > "$PHASE_LOG"

# ── 4. Extract Container Logs ────────────────────────────────────────
log "→ Capturing container logs..."
CONTAINER_LOG="$LOG_DIR/container_${TIMESTAMP}.log"
docker logs "$CONTAINER" --tail 500 --since 30m > "$CONTAINER_LOG" 2>&1

# ── 5. Validate UAT Pass Rate ────────────────────────────────────────
log "→ Validating UAT pass rate against threshold $UAT_PASS_RATE_THRESHOLD..."
UAT_PASS_RATE=$(echo "$STATUS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
metrics=d.get('metrics',{})
print(metrics.get('uat_pass_rate','0'))
" 2>/dev/null || echo "0")

UAT_VALID=$(python3 -c "
threshold = $UAT_PASS_RATE_THRESHOLD
rate = float('$UAT_PASS_RATE')
print('yes' if rate >= threshold else 'no')
" 2>/dev/null || echo "no")

if [ "$UAT_VALID" != "yes" ]; then
  log "⚠ UAT pass rate $UAT_PASS_RATE is below threshold $UAT_PASS_RATE_THRESHOLD"
else
  log "✓ UAT pass rate $UAT_PASS_RATE meets threshold $UAT_PASS_RATE_THRESHOLD"
fi

# ── 6. Generate Backlog ──────────────────────────────────────────────
log "→ Generating backlog..."
BACKLOG="$PROJECT_DIR/build/backlog.md"
mkdir -p "$PROJECT_DIR/build"

# Extract errors and warnings from logs
ERROR_COUNT=$(grep -ci 'error\|exception\|traceback' "$CONTAINER_LOG" 2>/dev/null || echo 0)
WARN_COUNT=$(grep -ci 'warning\|warn' "$CONTAINER_LOG" 2>/dev/null || echo 0)
PHASE_COUNT=$(echo "$STATUS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
phases=d.get('phases',{})
completed=sum(1 for v in phases.values() if v.get('status')=='complete')
print(completed)
" 2>/dev/null || echo 0)

cat > "$BACKLOG" <<BACKLOG_EOF
# Backlog — $PROJECT ($TIMESTAMP)

## Workflow Status
- Final status: $STATUS_VAL
- Phases completed: $PHASE_COUNT
- Errors in logs: $ERROR_COUNT
- Warnings in logs: $WARN_COUNT
- UAT pass rate: $UAT_PASS_RATE (threshold: $UAT_PASS_RATE_THRESHOLD)
- UAT validation: $([ "$UAT_VALID" = "yes" ] && echo "PASS" || echo "FAIL")

## Issues Found
BACKLOG_EOF

# Parse specific errors from logs
grep -i 'error\|exception\|failed\|crash' "$CONTAINER_LOG" 2>/dev/null | \
  tail -20 | while read -r line; do
    echo "- $line" >> "$BACKLOG"
done

cat >> "$BACKLOG" <<BACKLOG_EOF

## Fix Status
| # | Status | Agent | Notes |
|---|--------|-------|-------|

## Observations
- Pipeline run: $TIMESTAMP
- Container: $CONTAINER
- Log file: $CONTAINER_LOG
- Phase log: $PHASE_LOG
BACKLOG_EOF

log "→ Backlog written to $BACKLOG"

# ── 7. Summary ───────────────────────────────────────────────────────
log "========================================"
log "UAT Pipeline completed — $TIMESTAMP"
log "  Status: $STATUS_VAL"
log "  Phases completed: $PHASE_COUNT"
log "  Errors: $ERROR_COUNT | Warnings: $WARN_COUNT"
log "  UAT pass rate: $UAT_PASS_RATE (threshold: $UAT_PASS_RATE_THRESHOLD)"
log "  Backlog: $BACKLOG"
log "  Logs: $CONTAINER_LOG"
log "========================================"