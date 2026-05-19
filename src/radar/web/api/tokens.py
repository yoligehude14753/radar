"""凭证 / Token 管理 API — 交互式测试与持久化"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from radar.config import settings, ROOT_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

ENV_FILE = ROOT_DIR / ".env"


# ── 响应模型 ──────────────────────────────────────────────────────────────────


class TokenStatus(BaseModel):
    github_configured: bool
    reddit_configured: bool
    github_masked: str | None
    reddit_client_masked: str | None


class TestResult(BaseModel):
    ok: bool
    message: str


class SaveResult(BaseModel):
    ok: bool
    message: str


class RedditCredRequest(BaseModel):
    client_id: str
    client_secret: str
    username: str = ""
    password: str = ""


class GithubCredRequest(BaseModel):
    token: str


# ── 状态查询 ──────────────────────────────────────────────────────────────────


@router.get("/status", response_model=TokenStatus, summary="获取 Token 配置状态")
async def get_token_status() -> TokenStatus:
    gh = settings.github_token
    rid = settings.reddit_client_id
    return TokenStatus(
        github_configured=bool(gh),
        reddit_configured=bool(rid and settings.reddit_client_secret),
        github_masked=f"{gh[:8]}***" if len(gh) > 8 else (gh if gh else None),
        reddit_client_masked=f"{rid[:6]}***" if len(rid) > 6 else (rid if rid else None),
    )


# ── Reddit ────────────────────────────────────────────────────────────────────


@router.post("/reddit/test", response_model=TestResult, summary="测试 Reddit OAuth 凭证")
async def test_reddit(req: RedditCredRequest) -> TestResult:
    """用提供的凭证请求 Reddit access_token，验证是否有效。"""
    if not req.client_id or not req.client_secret:
        return TestResult(ok=False, message="client_id 和 client_secret 不能为空")

    grant_type = "password" if (req.username and req.password) else "client_credentials"
    data: dict[str, str] = {"grant_type": grant_type}
    if grant_type == "password":
        data["username"] = req.username
        data["password"] = req.password

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(req.client_id, req.client_secret),
                data=data,
                headers={"User-Agent": settings.reddit_user_agent},
            )
        if r.status_code == 200:
            body = r.json()
            if "access_token" in body:
                scope = body.get("scope", "")
                return TestResult(ok=True, message=f"认证成功 ✓  scope={scope}")
            error = body.get("error", "unknown")
            return TestResult(ok=False, message=f"认证失败: {error}")
        if r.status_code == 401:
            return TestResult(ok=False, message="client_id / client_secret 错误（401）")
        return TestResult(ok=False, message=f"HTTP {r.status_code}: {r.text[:200]}")
    except httpx.ConnectError:
        return TestResult(ok=False, message="无法连接 reddit.com，请检查网络或代理")
    except Exception as exc:
        logger.exception("Reddit token test failed")
        return TestResult(ok=False, message=f"测试出错: {exc}")


@router.post("/reddit/save", response_model=SaveResult, summary="保存 Reddit OAuth 凭证到 .env")
async def save_reddit(req: RedditCredRequest) -> SaveResult:
    updates: dict[str, str] = {
        "REDDIT_CLIENT_ID": req.client_id,
        "REDDIT_CLIENT_SECRET": req.client_secret,
    }
    if req.username:
        updates["REDDIT_USERNAME"] = req.username
    if req.password:
        updates["REDDIT_PASSWORD"] = req.password
    _patch_env(updates)
    return SaveResult(ok=True, message="已写入 .env，重启服务后生效")


# ── GitHub ────────────────────────────────────────────────────────────────────


@router.post("/github/test", response_model=TestResult, summary="测试 GitHub Personal Access Token")
async def test_github(req: GithubCredRequest) -> TestResult:
    if not req.token:
        return TestResult(ok=False, message="Token 不能为空")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"token {req.token}",
                    "User-Agent": "radar/0.1.0",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if r.status_code == 200:
            login = r.json().get("login", "unknown")
            remaining = r.headers.get("x-ratelimit-remaining", "?")
            return TestResult(ok=True, message=f"认证成功 ✓  用户: {login}  剩余速率: {remaining}/h")
        if r.status_code == 401:
            return TestResult(ok=False, message="Token 无效或已过期（401）")
        return TestResult(ok=False, message=f"HTTP {r.status_code}")
    except httpx.ConnectError:
        return TestResult(ok=False, message="无法连接 api.github.com，请检查网络")
    except Exception as exc:
        logger.exception("GitHub token test failed")
        return TestResult(ok=False, message=f"测试出错: {exc}")


@router.post("/github/save", response_model=SaveResult, summary="保存 GitHub Token 到 .env")
async def save_github(req: GithubCredRequest) -> SaveResult:
    _patch_env({"GITHUB_TOKEN": req.token})
    return SaveResult(ok=True, message="已写入 .env，重启服务后生效")


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _patch_env(updates: dict[str, str]) -> None:
    """安全地更新（或追加）.env 文件中的指定键值对。"""
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    touched: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            touched.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in touched:
            new_lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info("Patched .env: keys=%s", list(updates.keys()))
