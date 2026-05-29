"""E2E 测试：/api/eval/* 实测结果接口（heyi-eval 结果回流侧）

验收条件（用户可观察结果）：
  1. 无 heyi-eval 数据时返回空列表，不报错
  2. 写入 project/skill lane 的 state.json 后能列出，按时间倒序
  3. lane / outcome 过滤生效
  4. 详情含 agent 报告 + 日志尾
  5. 产物预览端点能取回媒体文件，且拒绝路径穿越
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient


def _write_run(root: Path, lane: str, run_id: str, **state) -> Path:
    run_dir = root / f"{lane}_lane" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    base = {"run_id": run_id, "status": "done"}
    base.update(state)
    (run_dir / "state.json").write_text(
        json.dumps(base, ensure_ascii=False), encoding="utf-8")
    return run_dir


@pytest.fixture()
def heyi_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "heyi-eval-data"
    root.mkdir()
    from radar.config import settings
    monkeypatch.setattr(settings, "heyi_eval_data", str(root))
    return root


@pytest.mark.asyncio
async def test_eval_results_empty(client: AsyncClient, heyi_root: Path) -> None:
    resp = await client.get("/api/eval/results")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_eval_results_list_and_sort(
    client: AsyncClient, heyi_root: Path,
) -> None:
    _write_run(
        heyi_root, "project", "proj-20260529-aaa",
        full_id="acme/agent", source_url="https://github.com/acme/agent",
        summary_outcome="pass", summary_deploys=True,
        enqueued_at="2026-05-29T01:00:00+00:00",
        candidate={"qag_score": 0.82},
    )
    _write_run(
        heyi_root, "skill", "skill-20260529-bbb",
        full_id="claude-user/mermaid", skill_path="/x/mermaid/SKILL.md",
        summary_outcome="partial", summary_demos_passed=3,
        enqueued_at="2026-05-29T02:00:00+00:00",
    )
    resp = await client.get("/api/eval/results")
    assert resp.status_code == 200
    data = resp.json()
    # newest enqueued_at first → skill before project
    assert [d["run_id"] for d in data] == [
        "skill-20260529-bbb", "proj-20260529-aaa"]
    proj = next(d for d in data if d["lane"] == "project")
    assert proj["outcome"] == "pass"
    assert proj["qag_score"] == 0.82


@pytest.mark.asyncio
async def test_eval_results_filters(client: AsyncClient, heyi_root: Path) -> None:
    _write_run(heyi_root, "project", "p1", full_id="a/b",
               summary_outcome="pass", enqueued_at="2026-05-29T01:00:00+00:00")
    _write_run(heyi_root, "skill", "s1", full_id="c/d",
               summary_outcome="fail", enqueued_at="2026-05-29T02:00:00+00:00")

    resp = await client.get("/api/eval/results", params={"lane": "skill"})
    assert [d["run_id"] for d in resp.json()] == ["s1"]

    resp = await client.get("/api/eval/results", params={"outcome": "pass"})
    assert [d["run_id"] for d in resp.json()] == ["p1"]


@pytest.mark.asyncio
async def test_eval_detail_with_report(
    client: AsyncClient, heyi_root: Path,
) -> None:
    run_dir = _write_run(
        heyi_root, "project", "proj-x", full_id="a/b",
        summary_outcome="pass", enqueued_at="2026-05-29T01:00:00+00:00")
    (run_dir / "report.json").write_text(json.dumps({
        "outcome": "pass",
        "verdict": {"core_features_demonstrated": ["cli"], "blockers": []},
        "self_assessment_zh": "跑通了 CLI",
    }), encoding="utf-8")
    (run_dir / "agent.log").write_text("step 1 ok\nstep 2 ok\n", encoding="utf-8")

    resp = await client.get("/api/eval/results/proj-x")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["full_id"] == "a/b"
    assert body["report"]["self_assessment_zh"] == "跑通了 CLI"
    assert "step 2 ok" in body["agent_log_tail"]

    # unknown run → 404
    resp = await client.get("/api/eval/results/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_eval_artifact_preview_and_traversal_guard(
    client: AsyncClient, heyi_root: Path,
) -> None:
    run_dir = _write_run(
        heyi_root, "skill", "skill-art", full_id="c/d",
        enqueued_at="2026-05-29T01:00:00+00:00")
    # a tiny fake png artifact
    art = run_dir / "showcase" / "out.png"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    # it shows up in the listing artifacts
    resp = await client.get("/api/eval/results")
    skill = next(d for d in resp.json() if d["run_id"] == "skill-art")
    assert "showcase/out.png" in skill["artifacts"]

    # preview works
    resp = await client.get("/api/eval/artifact/skill/skill-art/showcase/out.png")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\x89PNG")

    # path traversal is rejected at the resolver (the security-critical
    # seam; httpx normalizes ".." in URLs client-side so we assert the
    # guard directly rather than through the HTTP layer).
    from radar.eval import resolve_artifact
    assert resolve_artifact(
        str(heyi_root), "skill", "skill-art", "../../../etc/hosts") is None
    assert resolve_artifact(
        str(heyi_root), "skill", "skill-art", "showcase/out.png") is not None
