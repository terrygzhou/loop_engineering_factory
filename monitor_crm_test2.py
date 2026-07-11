#!/usr/bin/env python3
"""Monitor crm_test2 workflow execution end-to-end."""
import json
import subprocess
import time
import sys

STATUSES = []
ERRORS = []
PHASE_TRANSITIONS = []
START_TIME = time.time()
MAX_DURATION = 1800  # 30 minutes
INTERVAL = 15
MAX_CHECKS = 120  # cap at 120 checks

def curl_status():
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:8011/api/status"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None

def check_docker_logs():
    try:
        result = subprocess.run(
            ["docker", "logs", "loop_factory-loop-1", "--tail", "200", "2>&1"],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip()
    except Exception:
        return ""

def check_builder_logs():
    try:
        result = subprocess.run(
            ["docker", "logs", "loop_factory-builder-1", "--tail", "50", "2>&1"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""

prev_phase = None
prev_cycle = None

print("=== Loop Engineering UAT Monitor — crm_test2 ===")
print(f"Max duration: {MAX_DURATION}s, Poll interval: {INTERVAL}s\n")

for i in range(MAX_CHECKS):
    elapsed = time.time() - START_TIME
    if elapsed >= MAX_DURATION:
        print(f"\n⏱ Timeout reached ({elapsed:.0f}s)")
        break

    status = curl_status()
    if not status:
        print(f"  [{i+1:3d}] No status response")
        time.sleep(INTERVAL)
        continue

    phase = status.get("phase", "UNKNOWN")
    wf_status = status.get("status", "UNKNOWN")
    cycle = status.get("cycle", 0)
    waiting = status.get("waiting_for", "")
    messages = status.get("messages", [])

    # Track phase transitions
    if prev_phase is not None and (phase != prev_phase or cycle != prev_cycle):
        transition = f"{prev_phase}(c{prev_cycle}) → {phase}(c{cycle})"
        PHASE_TRANSITIONS.append(transition)
        print(f"  ★ PHASE TRANSITION: {transition}")
    elif prev_phase is None:
        PHASE_TRANSITIONS.append(f"START → {phase}(c{cycle})")

    prev_phase = phase
    prev_cycle = cycle

    # Check for new messages (progress events)
    new_msgs = [m for m in messages[-5:] if m.get("type") in ("event", "log", "phase_complete")]
    msg_summary = ""
    for m in new_msgs:
        msg_type = m.get("type", "?")
        msg_data = m.get("data", m.get("message", ""))
        if isinstance(msg_data, dict):
            msg_data = json.dumps(msg_data)
        if len(str(msg_data)) > 100:
            msg_data = str(msg_data)[:97] + "..."
        msg_summary += f"  → [{msg_type}] {msg_data}\n"

    # Log record
    record = {
        "check": i + 1,
        "elapsed_s": round(elapsed, 1),
        "status": wf_status,
        "phase": phase,
        "cycle": cycle,
        "waiting_for": waiting,
    }
    STATUSES.append(record)
    print(f"  [{i+1:3d}] {elapsed:7.1f}s | status={wf_status:10s} | phase={phase:10s} | cycle={cycle} | waiting={waiting}")

    if msg_summary:
        print(msg_summary)

    # Check container logs for errors
    logs = check_docker_logs()
    if logs:
        for line in logs.split('\n')[-30:]:
            line_lower = line.lower()
            if any(kw in line_lower for kw in ['error', 'traceback', 'exception', 'failed', 'syntaxerror', 'importerror']):
                if 'CancelledError' in line and 'non-fatal' in line:
                    continue
                if 'Deserializing unregistered' in line:
                    continue
                err_key = line.strip()[:200]
                if err_key not in ERRORS:
                    ERRORS.append(err_key)
                    print(f"  ⚠ LOG ERROR: {err_key[:150]}")

    # Check builder logs for BUILD phase progress
    if phase in ("BUILD",):
        bl = check_builder_logs()
        if bl:
            for line in bl.split('\n')[-10:]:
                if line.strip():
                    print(f"  [BUILD] {line.strip()[:150]}")

    # Check completion
    if wf_status == "complete":
        print(f"\n✓ Workflow COMPLETED in {elapsed:.1f}s!")
        break
    elif wf_status == "error":
        print(f"\n✗ Workflow ERRORED in {elapsed:.1f}s!")
        break
    elif wf_status == "idle" and prev_phase not in ("", None) and elapsed > 60:
        # If workflow went back to idle after running, something went wrong
        print(f"\n⚠ Workflow returned to idle after {elapsed:.1f}s")
        break

    time.sleep(INTERVAL)

# Final report
print("\n" + "=" * 60)
print("FINAL REPORT — crm_test2")
print("=" * 60)

if STATUSES:
    last = STATUSES[-1]
    print(f"Last status: {last['status']}")
    print(f"Phase: {last['phase']}")
    print(f"Cycle: {last['cycle']}")
    first = STATUSES[0]
    print(f"Total elapsed: {last['elapsed_s'] - first['elapsed_s']:.1f}s")
    print(f"Phase transitions: {len(PHASE_TRANSITIONS)}")
    for t in PHASE_TRANSITIONS:
        print(f"  {t}")
    print(f"Error lines in logs: {len(ERRORS)}")
else:
    print("No status data collected.")

if ERRORS:
    print(f"\n⚠ ERRORS/WARNINGS ({len(ERRORS)}):")
    for e in ERRORS[:20]:
        print(f"  {e[:200]}")
    if len(ERRORS) > 20:
        print(f"  ... and {len(ERRORS) - 20} more")

print(f"\nTotal monitoring time: {time.time() - START_TIME:.1f}s")
print("\nDone.")