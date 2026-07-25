#!/bin/bash
# Poll loop_factory workflow status every 30 seconds for up to 10 minutes
MAX_POLLS=20
POLL_INTERVAL=30
PREV_PHASES=""

for i in $(seq 1 $MAX_POLLS); do
    STATUS_JSON=$(curl -s http://localhost:8011/api/status)
    
    # Parse key fields
    STATUS=$(echo "$STATUS_JSON" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('status','?'))")
    PHASE=$(echo "$STATUS_JSON" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('phase','none'))")
    CYCLE=$(echo "$STATUS_JSON" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('cycle',0))")
    ERROR=$(echo "$STATUS_JSON" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('error',''))")
    WAITING=$(echo "$STATUS_JSON" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('waiting_for',''))")
    
    # Get detailed phase statuses
    CURRENT_PHASES=$(echo "$STATUS_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in d.get('phases',[]):
    if p['status'] != 'pending':
        print(f'{p[\"phase\"]}={p[\"status\"]}')
" | tr '\n' '|')
    
    # Detect phase transition
    if [ "$CURRENT_PHASES" != "$PREV_PHASES" ]; then
        echo ">>> TRANSITION: $CURRENT_PHASES"
    fi
    PREV_PHASES="$CURRENT_PHASES"
    
    echo "[$(date '+%H:%M:%S')] status=$STATUS phase=$PHASE cycle=$CYCLE waiting=$WAITING | $CURRENT_PHASES"
    
    if [ -n "$ERROR" ] && [ "$ERROR" != "" ]; then
        echo "*** ERROR: $ERROR"
    fi
    
    # Stop if completed or error
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "error" ] || [ "$STATUS" = "failed" ]; then
        echo "=== Workflow finished: $STATUS ==="
        exit 0
    fi
    
    sleep $POLL_INTERVAL
done

echo "=== Monitoring timeout reached (10 min) ==="