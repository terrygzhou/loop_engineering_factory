"""
Shared human review contract — used by both CLI executor and Web UI bridge.

Guarantees identical section definitions, labels, and return payload structure
across all HIL interfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

# Canonical section definitions — single source of truth for CLI & Web UI
REVIEW_SECTIONS: List[Dict[str, str]] = [
    {"key": "spec_refined", "label": "Specification"},
    {"key": "api_contract", "label": "API Contract"},
    {"key": "interview_notes", "label": "Interview Notes"},
    {"key": "plan", "label": "Implementation Plan"},
    {"key": "tasks", "label": "Task Breakdown"},
    {"key": "analysis", "label": "Cross-Artifact Analysis"},
    {"key": "doubt_resolution", "label": "Doubt Resolution"},
    {"key": "checklist", "label": "Feature Checklist"},
]


def build_review_sections(artifacts: Dict[str, str]) -> List[Dict[str, Any]]:
    """Build the full review payload from artifacts — identical for CLI & Web."""
    sections = []
    for sec in REVIEW_SECTIONS:
        key = sec["key"]
        text = artifacts.get(key, "")
        sections.append({
            "key": key,
            "label": sec["label"],
            "content": text,
            "word_count": len(text.split()) if text else 0,
        })
    return sections


def build_review_summary(sections: List[Dict[str, Any]]) -> Dict[str, str]:
    """One-line summary per section (key → description)."""
    return {s["key"]: f"{s['label']}: {s['word_count']} words" for s in sections}


def build_review_metrics(state: Any) -> Dict[str, float]:
    """Extract spec_confidence from state.metrics."""
    metrics = getattr(state, "metrics", None) or state.get("metrics", {})
    if metrics is None:
        return {"spec_confidence": 0.0}
    val = getattr(metrics, "spec_confidence", None)
    if val is None:
        val = metrics.get("spec_confidence", 0.0)
    return {"spec_confidence": float(val)}


def format_review_section_for_cli(title: str, content: str) -> str:
    """Terminal-friendly section formatting with ASCII separators."""
    sep = "-" * 60
    lines = [f"\n{sep}\n  {title}\n{sep}", content]
    return "\n".join(lines)


def format_review_summary_for_cli(sections: List[Dict[str, Any]]) -> str:
    """Terminal-friendly summary line per section."""
    return "\n".join(f"  [{s['label']}]: {s['word_count']} words" for s in sections)


@dataclass
class SectionFeedback:
    """Structured per-section review feedback — CLI and Web UI return this."""
    approved: bool = True
    edited: bool = False
    comment: str = ""
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None and v != ""}


@dataclass
class ReviewResult:
    """Return type for _cli_human_review — matches Web UI JSON payload exactly."""
    approved: bool
    section_feedback: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {"approved": self.approved, "section_feedback": self.section_feedback}


def make_review_result(section_feedback: Dict[str, Dict[str, Any]]) -> ReviewResult:
    """Build a ReviewResult from raw per-section feedback dicts."""
    all_approved = all(fb.get("approved", True) for fb in section_feedback.values())
    return ReviewResult(approved=all_approved, section_feedback=section_feedback)
