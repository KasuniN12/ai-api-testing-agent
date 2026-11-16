"""Persistence manager for storing run history, reports, and generated test files."""

from pathlib import Path
from typing import Any, Dict, List
import json
from config.settings import get_settings


class HistoryManager:
    """Manages saving and retrieving run history, reports, and generated code."""

    def __init__(self):
        self.settings = get_settings()
        self.reports_dir = Path(self.settings.REPORTS_DIR)
        self.tests_dir = Path(self.settings.GENERATED_TESTS_DIR)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, run_id: str, report_data: Dict[str, Any]) -> Path:
        """Save run report as a JSON file."""
        target = self.reports_dir / f"report_{run_id}.json"
        target.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        return target

    def save_test_suite_code(self, run_id: str, version: str, code: str) -> Path:
        """Save generated Pytest code to disk."""
        target = self.tests_dir / f"test_{run_id}_{version.lower()}.py"
        target.write_text(code, encoding="utf-8")
        return target

    def list_past_runs(self) -> List[str]:
        """List past run report IDs."""
        return [f.stem.replace("report_", "") for f in self.reports_dir.glob("report_*.json")]
