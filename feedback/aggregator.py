"""
Feedback aggregator: collect metrics and artifacts from each phase run.
"""
import json
from datetime import datetime
from pathlib import Path


class FeedbackAggregator:
    """Collects and stores feedback from workflow cycles."""

    def __init__(self, storage_dir: str = "./storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.cycles_dir = self.storage_dir / "cycles"
        self.cycles_dir.mkdir(exist_ok=True)

    def record_cycle(self, cycle_id: str, phase: str, metrics: dict,
                     artifacts: dict, feedback: list) -> dict:
        """Record a phase execution and return the cycle record."""
        record = {
            "cycle_id": cycle_id,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics,
            "artifacts": {k: v[:500] for k, v in artifacts.items()},  # Truncate for storage
            "feedback": feedback,
        }

        # Write to file
        filepath = self.cycles_dir / f"{cycle_id}.json"
        if filepath.exists():
            # Append to existing cycle
            with open(filepath, 'r') as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                # Convert single record to list
                existing = [existing]
            existing.append(record)
        else:
            existing = [record]

        with open(filepath, 'w') as f:
            json.dump(existing, f, indent=2)

        return record

    def get_cycle(self, cycle_id: str) -> list:
        """Get all records for a cycle."""
        filepath = self.cycles_dir / f"{cycle_id}.json"
        if not filepath.exists():
            return []
        with open(filepath, 'r') as f:
            return json.load(f)

    def list_cycles(self) -> list:
        """List all completed cycle IDs."""
        cycles = []
        for f in sorted(self.cycles_dir.glob("*.json")):
            cycles.append(f.stem)
        return cycles

    def get_historical_patterns(self, metric_name: str, threshold: float) -> list:
        """Find historical cycles where a metric exceeded a threshold."""
        patterns = []
        for f in self.cycles_dir.glob("*.json"):
            try:
                with open(f, 'r') as fh:
                    records = json.load(fh)
                for rec in records:
                    metrics = rec.get("metrics", {})
                    if isinstance(metrics, dict) and metrics.get(metric_name, 0) > threshold:
                        patterns.append(rec)
            except (json.JSONDecodeError, KeyError):
                continue
        return patterns
