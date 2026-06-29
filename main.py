"""
Loop Engineering CLI entry point.

Delegates to the shared executor so CLI and Web UI run identical workflow logic.
Usage:
    python main.py                      # interactive mode (asks for project name + spec)
    python main.py --project NAME       # auto-approve with given project name
    python main.py --project NAME --spec "text"  # with inline spec
    python main.py --project NAME --context /path  # scan existing codebase
"""
import argparse
import os
import sys
import time

from graph.executor import WorkflowRunner
from service.otel_instrumentor import tracer
from service import health as health_module
from log.logging import setup_logger, log_event

# Set env before logger init
os.environ.setdefault("LOG_LEVEL", "INFO")
logger = setup_logger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="Loop Engineering CLI")
    parser.add_argument("--project", type=str, default="", help="Project name")
    parser.add_argument("--spec", type=str, default="", help="Initial spec/idea text")
    parser.add_argument("--context", type=str, default="", help="Path to existing codebase for discovery")
    parser.add_argument("--auto-approve", action="store_true", help="Skip all HIL gates")
    parser.add_argument("--improve", action="store_true", help="Improve a previously deployed product (read live.json, skip interview)")
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Start observability ──
    tracer.configure()
    health_module.start_health_server()
    logger.info("CLI starting")

    if not args.project:
        name = input("Project name: ").strip()
    else:
        name = args.project

    if not name:
        logger.error("Project name is required")
        print("✗ Project name required. Use --project NAME or answer the prompt.")
        sys.exit(1)

    spec = args.spec
    if not spec:
        spec = input("Brief description (or Enter to skip): ").strip()

    context = args.context
    # Propagate --auto-approve to env so DISCOVER node can read it
    if args.auto_approve:
        os.environ["AUTO_APPROVE"] = "true"

    if not context and not args.auto_approve:
        context = input("Existing codebase path for discovery (or Enter for greenfield): ").strip()

    # ── Trace workflow lifecycle ──
    tracer.start_workflow(project_name=name, spec_text=spec)
    health_module.track_workflow_start(name)
    start = time.time()

    log_event(logger, "workflow.started", project=name, spec=spec[:100], context=context or "", improve=args.improve)
    mode = "IMPROVE" if args.improve else "NEW"
    print(f"\n=== Loop Engineering — {mode} [{name}] ===")

    runner = WorkflowRunner(auto_approve=args.auto_approve)
    result = runner.run_interactive(
        project_name=name,
        spec_text=spec,
        context_folder=context,
        auto_approve=args.auto_approve,
        improve_mode=args.improve,
    )

    duration = round(time.time() - start, 1)
    health_module.track_workflow_end(name, duration)

    print(f"\n=== Cycle {result.get('cycle_id', '?')} complete ({duration}s) ===")
    print(f"Phase: {result.get('phase')}")
    print(f"Project: {result.get('artifacts', {}).get('project_name', 'unknown')}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Feedback entries: {len(result.get('feedback', []))}")

    # ── Close trace ──
    status = "error" if result.get("error") else "completed"
    tracer.end_workflow(status=status, error=result.get("error"))
    log_event(logger, "workflow.finished", project=name, duration_s=duration, status=status)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception("Workflow failed")
        print(f"\n✗ Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
