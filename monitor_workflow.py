#!/usr/bin/env python3
"""Monitor Loop Engineering workflow for crm_test1."""
import json
import subprocess
import time
import sys

STATUSES = []
ERRORS = []
PHASE_TRANSITIONS = []
START_TIME = time.time()
MAX_DURATION = 300  # 5 minutes
INTERVAL = 30
CHECKS = 10

def run_cmd(cmd, timeout=15):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 1

def check_status():
    out, err, code = run_cmd("curl -s http://localhost:8011/api/status")
    if out:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
    return None

def check_logs():
    out, err, code = run_cmd("docker logs loop_factory-loop-1 --tail 100 2>&1")
    return out

def check_phoenix():
    out, err, code = run_cmd("curl -s 'http://localhost:6006/api/trace?service_name=loop-orchestrator' 2>/dev/null")
    if out:
        try:
            data = json.loads(out)
            if isinstance(data, list):
                return len(data)
            elif isinstance(data, dict):
                return data.get('total', data.get('count', 0))
        except (json.JSONDecodeError, TypeError):
            pass
    return 0

print("=== Loop Engineering Workflow Monitor ===")
print(f"Project: crm_test1")
print(f"Duration: {MAX_DURATION}s, Interval: {INTERVAL}s\n")

prev_phase = None
prev_cycle = None

for i in range(CHECKS):
    elapsed = time.time() - START_TIME
    if elapsed >= MAX_DURATION:
        break

    status = check_status()
    logs = check_logs()

    if status:
        phase = status.get("phase", "UNKNOWN")
        cycle = status.get("cycle", 0)
        wf_status = status.get("status", "UNKNOWN")

        # Track phase transitions
        if prev_phase is not None and (phase != prev_phase or cycle != prev_cycle):
            transition = f"{prev_phase}(c{prev_cycle}) → {phase}(c{cycle})"
            PHASE_TRANSITIONS.append(transition)
            print(f"  [TRANSITION] {transition}")

        if prev_phase is None:
            PHASE_TRANSITIONS.append(f"START → {phase}(c{cycle})")

        prev_phase = phase
        prev_cycle = cycle

        # Scan logs for errors
        error_lines = []
        for line in logs.split('\n'):
            line_lower = line.lower()
            if any(kw in line_lower for kw in ['error', 'traceback', 'exception', 'failed', '500']):
                # Filter out known benign patterns
                if 'CancelledError' in line and 'non-fatal' in line:
                    continue
                if 'Deserializing unregistered type' in line:
                    continue
                if any(kw in line_lower for kw in ['error', 'traceback', 'exception']):
                    error_lines.append(line.strip())

        new_errors = [e for e in error_lines if e not in ERRORS]
        ERRORS.extend(new_errors)
        if new_errors:
            print(f"  ⚠ {len(new_errors)} new error/warning line(s) in logs")

        phoenix_traces = check_phoenix()

        record = {
            "check": i + 1,
            "elapsed_s": round(elapsed, 1),
            "status": wf_status,
            "phase": phase,
            "cycle": cycle,
            "errors_in_logs": len(ERRORS),
            "phoenix_traces": phoenix_traces,
        }
        STATUSES.append(record)
        print(f"  [{i+1:2d}] {elapsed:6.1f}s | status={wf_status:10s} | phase={phase:10s} | cycle={cycle} | errors={len(ERRORS)} | traces={phoenix_traces}")

        if wf_status == "completed":
            print(f"\n✓ Workflow completed in {elapsed:.1f}s!")
            break
        elif wf_status == "error":
            print(f"\n✗ Workflow encountered errors!")
            break
    else:
        print(f"  [{i+1:2d}] No status response (service may be starting)")

    # Sleep for interval (unless last iteration)
    remaining = MAX_DURATION - elapsed - INTERVAL
    if remaining > 0 and i < CHECKS - 1:
        time.sleep(INTERVAL)

# Final report
print("\n" + "=" * 60)
print("FINAL REPORT")
print("=" * 60)

if STATUSES:
    last = STATUSES[-1]
    print(f"Last status: {last['status']}")
    print(f"Phase: {last['phase']}")
    print(f"Cycle: {last['cycle']}")
    print(f"Phase transitions: {len(PHASE_TRANSITIONS)}")
    for t in PHASE_TRANSITIONS:
        print(f"  {t}")
    print(f"Total error lines in logs: {len(ERRORS)}")
    print(f"Phoenix traces: {last.get('phoenix_traces', 'N/A')}")
else:
    print("No status data collected.")

if ERRORS:
    print(f"\n⚠ ERROR/WARNING LINES ({len(ERRORS)}):")
    for e in ERRORS[:20]:  # Cap at 20
        print(f"  {e[:200]}")
    if len(ERRORS) > 20:
        print(f"  ... and {len(ERRORS) - 20} more")

print(f"\nCompleted after {time.time() - START_TIME:.1f}s")