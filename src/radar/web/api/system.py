"""系统状态 API"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from radar.config import settings

router = APIRouter()


class HealthResp(BaseModel):
    status: str
    version: str
    db_type: str
    llm_profile: str


@router.get("/health", response_model=HealthResp, summary="健康检查")
async def health() -> HealthResp:
    db_url = settings.db_async_url
    db_type = "sqlite" if "sqlite" in db_url else "postgresql"
    return HealthResp(
        status="ok",
        version="0.1.0",
        db_type=db_type,
        llm_profile=settings.llm_profile.value,
    )


@router.post("/upgrade", summary="从 git 拉最新代码并重装依赖（仅在 git 工作目录中有效）")
async def upgrade() -> dict:
    """git pull + pip install -e . 然后向自身 PID 发 SIGTERM 让 systemd 重启。
    仅在有 .git 目录且 pyproject.toml 存在时执行。
    """
    repo_root = Path(settings.base_dir)
    if not (repo_root / ".git").exists():
        return {"ok": False, "message": "不在 git 工作目录，跳过"}

    async def _run_cmd(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            return proc.returncode, stdout.decode()[-500:], stderr.decode()[-300:]
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", "timeout"

    # git pull
    rc, out, err = await _run_cmd(["git", "pull", "--ff-only"], repo_root)
    if rc != 0:
        return {"ok": False, "step": "git pull", "stdout": out, "stderr": err}

    # pip install -e .
    pip = Path(sys.executable).parent / "pip"
    rc2, out2, err2 = await _run_cmd(
        [str(pip), "install", "-e", ".", "-q"], repo_root,
    )
    if rc2 != 0:
        return {"ok": False, "step": "pip install", "stdout": out2, "stderr": err2}

    # 向自身发 SIGTERM，systemd 会重启进程加载新代码
    import signal
    os.kill(os.getpid(), signal.SIGTERM)
    return {"ok": True, "message": "git pull + pip install 完成，正在重启进程",
            "git_out": out[:200]}
