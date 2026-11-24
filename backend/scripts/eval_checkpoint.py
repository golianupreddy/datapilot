"""Per-case checkpointing for eval runs, so an interrupted run resumes instead of restarting."""
import json
from pathlib import Path


class Checkpoint:
    def __init__(self, path: str, resume: bool = True, retry_infra: bool = True) -> None:
        self.path = Path(path)
        self.data: dict[str, dict] = {}
        if resume and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if retry_infra:
                self.data = {k: v for k, v in self.data.items() if not v.get("infra_error")}

    def get(self, case_id: str):
        return self.data.get(case_id)

    def put(self, case_id: str, record: dict) -> None:
        self.data[case_id] = record
        self.path.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def split_scored(records: list[dict]) -> tuple[list[dict], int]:
    """Cases hit by LLM outages must not count as wrong answers."""
    scored = [r for r in records if not r.get("infra_error")]
    return scored, len(records) - len(scored)
