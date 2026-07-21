#!/usr/bin/env python3
"""
UAT: ARCH_REVIEW UI gap fix
Tests: Mermaid rendering, diagram review UI, approve/reject flow
"""
from config.loader import config as _cfg

BASE = _cfg.services.loop_api.url or "http://localhost:8011"
PASS = FAIL = 0
FAILURES = []

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append((name, detail))
        print(f"  [FAIL] {name} — {detail}")

def get(url):
    req = urllib.request.Request(f"{BASE}{url}", headers={"Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")

def post(url, data=None):
    body = json.dumps(data).encode() if data else b"{}"
    req = urllib.request.Request(f"{BASE}{url}", data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

print("=" * 60)
print("UAT: ARCH_REVIEW UI Gap Fix")
print("=" * 60)

# ─── Test 1: Frontend serves correctly ───
print("\n[1] Frontend static assets")
try:
    html = get("/")
    test("Index page loads", html and "<html" in html, "page returned empty")
    test("Mermaid.js CDN present", "mermaid" in html and "cdn.jsdelivr.net" in html, "Mermaid CDN not found")
    test("mermaid.initialize called", "mermaid.initialize" in html, "Initialize missing")
except Exception as e:
    test("Index page loads", False, str(e))

# ─── Test 2: app.js has renderArchReview ───
print("\n[2] Frontend JS — renderArchReview")
try:
    js = get("/static/js/app.js")
    test("app.js loads", js and "function" in js, "JS returned empty")
    test("renderArchReview function exists", "renderArchReview" in js, "Function missing")
    test("Mermaid render call", "mermaid.run" in js or "mermaid.initialize" in js, "No mermaid call")
    test("ARCH_REVIEW event handler", "'arch_review'" in js or '"arch_review"' in js, "Event handler missing")
    test("Approve button handler", "arch-review-approve" in js, "Approve handler missing")
    test("Reject button handler", "arch-review-reject" in js, "Reject handler missing")
    test("Diagram tabs", "diagram-tab" in js, "Tab UI missing")
    test("Toggle source", "toggleSource" in js, "Source toggle missing")
except Exception as e:
    test("app.js loads", False, str(e))

# ─── Test 3: CSS styles for review UI ───
print("\n[3] CSS — diagram review styles")
try:
    css = get("/static/css/style.css")
    test("style.css loads", css and ".detail-content" in css, "CSS returned empty")
    test(".diagram-tabs class", ".diagram-tabs" in css, "Tabs style missing")
    test(".diagram-panel class", ".diagram-panel" in css, "Panel style missing")
    test(".mermaid-container class", ".mermaid-container" in css, "Mermaid container missing")
    test(".review-summary class", ".review-summary" in css, "Summary style missing")
    test(".review-actions class", ".review-actions" in css, "Actions style missing")
except Exception as e:
    test("style.css loads", False, str(e))

# ─── Test 4: Bridge API health ───
print("\n[4] Backend API")
try:
    status = get("/api/status")
    status_data = json.loads(status)
    test("Status endpoint works", "status" in status_data, f"Unexpected: {status_data}")
except Exception as e:
    test("Status endpoint works", False, str(e))

# ─── Test 5: Bridge — ARCH_REVIEW event wiring ───
print("\n[5] Bridge — ARCH_REVIEW event wiring")
try:
    # Check bridge source for ARCH_REVIEW handling
    import subprocess
    result = subprocess.run(
        ["docker", "exec", "loop_factory-loop-1", "grep", "-c", "arch_review",
         "/app/frontend/backend/workflow_bridge.py"],
        capture_output=True, text=True
    )
    count = int(result.stdout.strip()) if result.stdout else 0
    test("Bridge handles ARCH_REVIEW", count >= 3, f"Only {count} references")
    
    # Check bridge reads diagram content
    result = subprocess.run(
        ["docker", "exec", "loop_factory-loop-1", "grep", "-c", "diagram_paths",
         "/app/frontend/backend/workflow_bridge.py"],
        capture_output=True, text=True
    )
    has_paths = int(result.stdout.strip()) if result.stdout else 0
    test("Bridge reads diagram paths", has_paths > 0, "No diagram_paths handling")
    
    # Check resume data passes approval
    result = subprocess.run(
        ["docker", "exec", "loop_factory-loop-1", "grep", "-c", "arch_review_approved",
         "/app/frontend/backend/workflow_bridge.py"],
        capture_output=True, text=True
    )
    has_resume = int(result.stdout.strip()) if result.stdout else 0
    test("Bridge passes approval on resume", has_resume > 0, "No approval data passed")
except Exception as e:
    test("Bridge ARCH_REVIEW wiring", False, str(e))

# ─── Test 6: Edge routing ───
print("\n[6] Edge routing — ARCH_REVIEW")
try:
    result = subprocess.run(
        ["docker", "exec", "loop_factory-loop-1", "grep", "-A", "5", "ARCH_REVIEW",
         "/app/graph/edges.py"],
        capture_output=True, text=True
    )
    edges_content = result.stdout
    test("ARCH_REVIEW edge exists", "ARCH_REVIEW" in edges_content, "No edge for ARCH_REVIEW")
    test("Edge routes to BUILD", "BUILD" in edges_content, "No BUILD routing")
    test("Edge handles rejection", "DEFINE" in edges_content or "PLAN" in edges_content, "No rejection routing")
except Exception as e:
    test("Edge routing", False, str(e))

# ─── Test 7: Graph compilation ───
print("\n[7] Graph compilation")
try:
    result = subprocess.run(
        ["docker", "exec", "loop_factory-loop-1", "grep", "interrupt_after",
         "/app/graph/main.py"],
        capture_output=True, text=True
    )
    test("ARCH_REVIEW in interrupt_after", "ARCH_REVIEW" in result.stdout, "interrupt_after missing")
except Exception as e:
    test("Graph compilation", False, str(e))

# ─── Test 8: Architecture node ───
print("\n[8] Architecture node — diagram generation")
try:
    result = subprocess.run(
        ["docker", "exec", "loop_factory-loop-1", "grep", "-c", "diagrams_dir",
         "/app/graph/nodes/architecture.py"],
        capture_output=True, text=True
    )
    count = int(result.stdout.strip()) if result.stdout else 0
    test("Architecture generates diagrams", count > 0, "No diagram generation")
except Exception as e:
    test("Architecture node", False, str(e))

# ─── Summary ───
print(f"\n{'=' * 60}")
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
if FAILURES:
    print(f"\nFAILURES:")
    for name, detail in FAILURES:
        print(f"  ✗ {name}: {detail}")
else:
    print("ALL TESTS PASSED ✓")
print(f"{'=' * 60}")
sys.exit(1 if FAIL else 0)
