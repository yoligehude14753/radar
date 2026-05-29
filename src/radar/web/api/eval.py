"""heyi-eval 实测结果 API（radar×heyi-eval 合并：结果回流侧）。

只读 heyi-eval 落盘的 project/skill lane run，归一化后给前端
「实测结果」页。包含列表、详情（含 agent 报告 + 日志尾）、以及
图片/音频/视频产物的预览端点。
"""
from __future__ import annotations

import mimetypes
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from radar.config import settings
from radar.eval import list_results, load_result_detail, resolve_artifact

router = APIRouter()


class EvalResultResp(BaseModel):
    run_id: str
    lane: str
    full_id: str
    target: str
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
    artifacts: list[str]


@router.get("/results", response_model=list[EvalResultResp], summary="实测结果列表")
async def eval_results(
    lane: Optional[str] = Query(None, description="project / skill / model"),
    outcome: Optional[str] = Query(None, description="pass / partial / fail / ..."),
    limit: int = Query(200, ge=1, le=1000),
) -> list[EvalResultResp]:
    rows = list_results(
        settings.heyi_eval_data, lane=lane, outcome=outcome, limit=limit,
    )
    return [EvalResultResp(**r.to_dict()) for r in rows]


@router.get("/results/{run_id}", summary="实测结果详情（含 agent 报告 + 日志尾）")
async def eval_result_detail(run_id: str) -> dict:
    detail = load_result_detail(settings.heyi_eval_data, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"未找到评测 run: {run_id}")
    return detail


@router.get("/artifact/{lane}/{run_id}/{rel:path}", summary="产物预览（图片/音视频）")
async def eval_artifact(lane: str, run_id: str, rel: str) -> FileResponse:
    path = resolve_artifact(settings.heyi_eval_data, lane, run_id, rel)
    if path is None:
        raise HTTPException(status_code=404, detail="产物不存在或路径非法")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "application/octet-stream")
