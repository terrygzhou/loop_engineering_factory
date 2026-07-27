"""
Skill progress bridge — nodes use this to report skill invocations
to the UI via WebSocket. When skill_callback is available (Web UI mode),
events are broadcast in real-time.
"""
import time


def report_skill_running(state: dict, skill_name: str):
    """Report that a skill invocation has started."""
    cb = state.get("skill_callback")
    if cb:
        cb(skill_name, "running")


def report_skill_completed(state: dict, skill_name: str, duration_s: float = 0, details: dict = None):
    """Report that a skill invocation has completed."""
    cb = state.get("skill_callback")
    if cb:
        cb(skill_name, "completed", {"duration_s": duration_s, **(details or {})})


def report_skill_failed(state: dict, skill_name: str, error: str = ""):
    """Report that a skill invocation failed."""
    cb = state.get("skill_callback")
    if cb:
        cb(skill_name, "failed", {"error": error})


class SkillTimer:
    """Context manager that auto-reports skill running → completed."""
    def __init__(self, state: dict, skill_name: str):
        self.state = state
        self.skill_name = skill_name
        self.start = time.time()
        report_skill_running(state, skill_name)

    def complete(self, duration_s: float = None, details: dict = None):
        elapsed = duration_s or (time.time() - self.start)
        report_skill_completed(self.state, self.skill_name, elapsed, details)

    def fail(self, error: str = ""):
        report_skill_failed(self.state, self.skill_name, error)