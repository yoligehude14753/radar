"""Read + normalize heyi-eval lane results from disk.

heyi-eval owns the data; radar only reads it (co-located filesystem).
We deliberately do NOT import heyi-eval's Python — the contract is the
on-disk JSON shape, so the two codebases stay decoupled and radar can
run with just its own deps.

Layout (per heyi-eval):

    {root}/project_lane/runs/<run_id>/state.json   # ProjectRun.to_jsonable()
    {root}/project_lane/runs/<run_id>/report.json  # agent RunReport (optional)
    {root}/project_lane/runs/<run_id>/agent.log    # agent stdout (optional)
    {root}/skill_lane/runs/<run_id>/...            # same shape, SkillRun

``state.json`` keys we rely on (others ignored): run_id, full_id,
source_url / skill_path, status, summary_outcome, summary_deploys,
summary_quickstart, summary_demos_passed, enqueued_at, started_at,
ended_at, failure_reason_zh, candidate{...}.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Image/audio/video extensions we surface as previewable artifacts.
_PREVIEW_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".mp3", ".wav", ".ogg", ".m4a",
    ".mp4", ".webm", ".mov",
}
_LANES = ("project", "skill", "model")


@dataclass
class EvalResult:
    run_id: str
    lane: str
    full_id: str
    target: str            # source_url (project) or skill_path (skill)
    status: str
    outcome: Optional[str]
    deploys: Optional[bool]
    quickstart_works: Optional[bool]
    demos_passed: Optional[int]
    enqueued_at: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    failure_reason_zh: Optional[str]
    qag_score: Optional[float]
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "lane": self.lane,
            "full_id": self.full_id,
            "target": self.target,
            "status": self.status,
            "outcome": self.outcome,
            "deploys": self.deploys,
            "quickstart_works": self.quickstart_works,
            "demos_passed": self.demos_passed,
            "enqueued_at": self.enqueued_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "failure_reason_zh": self.failure_reason_zh,
            "qag_score": self.qag_score,
            "artifacts": self.artifacts,
        }


def _runs_dir(root: Path, lane: str) -> Path:
    return root / f"{lane}_lane" / "runs"


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _qag_from_candidate(candidate: Any) -> Optional[float]:
    if isinstance(candidate, dict):
        v = candidate.get("qag_score")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _find_artifacts(run_dir: Path, *, cap: int = 24) -> list[str]:
    """Return run-dir-relative paths of previewable media, capped."""
    out: list[str] = []
    for p in sorted(run_dir.rglob("*")):
        if len(out) >= cap:
            break
        if p.is_file() and p.suffix.lower() in _PREVIEW_EXTS:
            out.append(str(p.relative_to(run_dir)))
    return out


def _state_to_result(lane: str, state: dict[str, Any], run_dir: Path) -> EvalResult:
    target = state.get("source_url") or state.get("skill_path") or ""
    return EvalResult(
        run_id=state.get("run_id", run_dir.name),
        lane=lane,
        full_id=state.get("full_id", ""),
        target=target,
        status=state.get("status", "unknown"),
        outcome=state.get("summary_outcome"),
        deploys=state.get("summary_deploys"),
        quickstart_works=state.get("summary_quickstart"),
        demos_passed=state.get("summary_demos_passed"),
        enqueued_at=state.get("enqueued_at"),
        started_at=state.get("started_at"),
        ended_at=state.get("ended_at"),
        failure_reason_zh=(state.get("failure_reason_zh") or None),
        qag_score=_qag_from_candidate(state.get("candidate")),
        artifacts=_find_artifacts(run_dir),
    )


def list_results(
    root: str | Path,
    *,
    lane: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 200,
) -> list[EvalResult]:
    """List normalized eval results, newest-first by enqueued_at.

    Missing lane dirs are treated as empty (heyi-eval may not have run a
    given lane yet). Unreadable/partial state.json files are skipped.
    """
    root = Path(root)
    lanes = [lane] if lane in _LANES else _LANES
    results: list[EvalResult] = []
    for ln in lanes:
        runs_dir = _runs_dir(root, ln)
        if not runs_dir.is_dir():
            continue
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            state = _read_json(run_dir / "state.json")
            if not state:
                continue
            res = _state_to_result(ln, state, run_dir)
            if outcome and (res.outcome or res.status) != outcome:
                continue
            results.append(res)
    results.sort(key=lambda r: (r.enqueued_at or ""), reverse=True)
    return results[:limit]


def load_result_detail(root: str | Path, run_id: str) -> Optional[dict[str, Any]]:
    """Full detail for one run: normalized summary + agent report +
    agent.log tail. Returns None if the run_id isn't found in any lane.
    """
    root = Path(root)
    for ln in _LANES:
        run_dir = _runs_dir(root, ln) / run_id
        state = _read_json(run_dir / "state.json")
        if not state:
            continue
        res = _state_to_result(ln, state, run_dir)
        report = _read_json(run_dir / "report.json")
        log_path = run_dir / "agent.log"
        agent_log_tail = None
        if log_path.exists():
            try:
                agent_log_tail = log_path.read_text(
                    encoding="utf-8", errors="replace"
                )[-12_000:]
            except OSError:
                agent_log_tail = None
        return {
            "summary": res.to_dict(),
            "report": report,
            "agent_log_tail": agent_log_tail,
        }
    return None


def resolve_artifact(root: str | Path, lane: str, run_id: str, rel: str) -> Optional[Path]:
    """Resolve a run-dir-relative artifact path to an absolute path,
    guarding against path traversal. Returns None if invalid/missing.
    """
    if lane not in _LANES:
        return None
    run_dir = (_runs_dir(Path(root), lane) / run_id).resolve()
    target = (run_dir / rel).resolve()
    try:
        target.relative_to(run_dir)
    except ValueError:
        return None  # traversal attempt
    if target.is_file():
        return target
    return None
