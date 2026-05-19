"""系统设置 API — 数据源配置、LLM 模型服务配置"""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from radar.config import settings
from radar.web.api.tokens import _patch_env

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_INTERVALS = ["15min", "30min", "1h", "3h", "6h", "12h", "daily", "weekly"]
VALID_PROFILES = ["yunwu", "heyi", "ollama", "openai"]


# ── 响应模型 ──────────────────────────────────────────────────────────────────


class SourceConfig(BaseModel):
    enabled: bool          # 实际有效状态 = env_enabled AND prerequisites_met
    env_enabled: bool      # .env 里的开关值
    interval: str
    description: str
    prerequisites_met: bool         # 运行前提是否全部满足
    missing_prerequisite: str | None  # 缺失配置的说明文字


class LLMProfileConfig(BaseModel):
    profile: Literal["yunwu", "heyi", "ollama", "openai"]
    model: str
    base_url: str
    api_key_masked: str


class SettingsOverview(BaseModel):
    # 数据源
    github: SourceConfig
    reddit: SourceConfig
    # LLM
    active_profile: str
    yunwu: LLMProfileConfig
    heyi: LLMProfileConfig
    ollama: LLMProfileConfig
    openai: LLMProfileConfig
    # 限制
    max_items_per_run: int
    report_projects_cron: str
    report_communities_cron: str


class UpdateSourcesRequest(BaseModel):
    github_enabled: bool = True
    github_interval: str = "6h"
    reddit_enabled: bool = True
    reddit_interval: str = "1h"


class UpdateLLMRequest(BaseModel):
    profile: str
    model: str = ""
    base_url: str = ""
    api_key: str = ""  # 空字符串表示不更改


class TestLLMResult(BaseModel):
    ok: bool
    message: str
    model_used: str = ""


# ── 读取当前设置 ──────────────────────────────────────────────────────────────


@router.get("/overview", response_model=SettingsOverview, summary="获取当前系统设置")
async def get_settings_overview() -> SettingsOverview:
    def mask(key: str) -> str:
        return f"{key[:8]}***" if len(key) > 8 else ("已配置" if key else "未配置")

    import os
    github_env_enabled = os.environ.get("GITHUB_ENABLED", "true").lower() != "false"
    reddit_env_enabled = os.environ.get("REDDIT_ENABLED", "true").lower() != "false"

    # GitHub：无 Token 也能运行（速率降至 60 次/h），前提条件始终满足
    github_prereq = True
    github_missing: str | None = None

    # Reddit：必须有 client_id + client_secret，否则 403 全部失败
    reddit_prereq = bool(settings.reddit_client_id and settings.reddit_client_secret)
    reddit_missing: str | None = (
        None if reddit_prereq else
        "需要先在「凭证管理」中配置 Reddit OAuth App（client_id + client_secret）"
    )

    return SettingsOverview(
        github=SourceConfig(
            enabled=github_env_enabled and github_prereq,
            env_enabled=github_env_enabled,
            interval=settings.github_crawl_interval,
            description="GitHub Trending / 关键词搜索",
            prerequisites_met=github_prereq,
            missing_prerequisite=github_missing,
        ),
        reddit=SourceConfig(
            enabled=reddit_env_enabled and reddit_prereq,
            env_enabled=reddit_env_enabled,
            interval=settings.reddit_crawl_interval,
            description="r/MachineLearning · r/artificial 等 13 个社区",
            prerequisites_met=reddit_prereq,
            missing_prerequisite=reddit_missing,
        ),
        active_profile=settings.llm_profile.value,
        yunwu=LLMProfileConfig(
            profile="yunwu",
            model=settings.yunwu_model,
            base_url=settings.yunwu_base_url,
            api_key_masked=mask(settings.yunwu_api_key),
        ),
        heyi=LLMProfileConfig(
            profile="heyi",
            model=settings.heyi_model,
            base_url=settings.heyi_base_url,
            api_key_masked=mask(settings.heyi_api_key),
        ),
        ollama=LLMProfileConfig(
            profile="ollama",
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            api_key_masked="本地服务，无需 Key",
        ),
        openai=LLMProfileConfig(
            profile="openai",
            model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            api_key_masked=mask(settings.llm_api_key if settings.llm_profile.value == "openai" else ""),
        ),
        max_items_per_run=settings.max_items_per_run,
        report_projects_cron=settings.report_projects_cron,
        report_communities_cron=settings.report_communities_cron,
    )


# ── 更新数据源配置 ─────────────────────────────────────────────────────────────


@router.post("/sources", summary="更新数据源配置（写入 .env）")
async def update_sources(req: UpdateSourcesRequest) -> dict:
    if req.github_interval not in VALID_INTERVALS:
        return {"ok": False, "message": f"无效的间隔: {req.github_interval}，可用: {VALID_INTERVALS}"}
    if req.reddit_interval not in VALID_INTERVALS:
        return {"ok": False, "message": f"无效的间隔: {req.reddit_interval}，可用: {VALID_INTERVALS}"}

    _patch_env({
        "GITHUB_ENABLED": "true" if req.github_enabled else "false",
        "GITHUB_CRAWL_INTERVAL": req.github_interval,
        "REDDIT_ENABLED": "true" if req.reddit_enabled else "false",
        "REDDIT_CRAWL_INTERVAL": req.reddit_interval,
    })
    logger.info("数据源配置已更新: github=%s/%s reddit=%s/%s",
                req.github_enabled, req.github_interval,
                req.reddit_enabled, req.reddit_interval)
    return {"ok": True, "message": "数据源配置已保存到 .env，重启服务后生效"}


# ── 更新 LLM 配置 ─────────────────────────────────────────────────────────────


@router.post("/llm", summary="更新 LLM 模型服务配置（写入 .env）")
async def update_llm(req: UpdateLLMRequest) -> dict:
    if req.profile not in VALID_PROFILES:
        return {"ok": False, "message": f"无效的 Profile: {req.profile}"}

    updates: dict[str, str] = {"LLM_PROFILE": req.profile}

    prefix_map = {
        "yunwu": ("YUNWU_API_KEY", "YUNWU_BASE_URL", "YUNWU_MODEL"),
        "heyi": ("HEYI_API_KEY", "HEYI_BASE_URL", "HEYI_MODEL"),
        "ollama": ("OLLAMA_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL"),
        "openai": ("OPENAI_API_KEY", None, None),
    }
    key_k, url_k, model_k = prefix_map[req.profile]

    if req.api_key and key_k:
        updates[key_k] = req.api_key
    if req.base_url and url_k:
        updates[url_k] = req.base_url
    if req.model and model_k:
        updates[model_k] = req.model

    _patch_env(updates)
    logger.info("LLM 配置已更新: profile=%s model=%s", req.profile, req.model)
    return {"ok": True, "message": f"LLM 配置已保存，切换到 {req.profile}，重启服务后生效"}


# ── 测试 LLM 连通性 ────────────────────────────────────────────────────────────


@router.post("/llm/test", response_model=TestLLMResult, summary="测试 LLM 服务连通性")
async def test_llm(req: UpdateLLMRequest) -> TestLLMResult:
    """用提供的参数（或当前配置）向 LLM 发一条 ping 请求。"""
    profile = req.profile if req.profile in VALID_PROFILES else settings.llm_profile.value

    # 确定实际要用的参数
    base_url = req.base_url or _get_base_url(profile)
    api_key = req.api_key or _get_api_key(profile)
    model = req.model or _get_model(profile)

    if not base_url:
        return TestLLMResult(ok=False, message="base_url 为空，请先配置")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
            )
        if r.status_code == 200:
            data = r.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            used_model = data.get("model", model)
            return TestLLMResult(ok=True, message=f"连接成功 ✓  回复: {reply!r}", model_used=used_model)
        return TestLLMResult(ok=False, message=f"HTTP {r.status_code}: {r.text[:300]}")
    except httpx.ConnectError as e:
        return TestLLMResult(ok=False, message=f"无法连接到 {base_url}，请检查地址和网络: {e}")
    except Exception as exc:
        logger.exception("LLM test failed")
        return TestLLMResult(ok=False, message=f"测试出错: {exc}")


def _get_base_url(profile: str) -> str:
    mapping = {
        "yunwu": settings.yunwu_base_url,
        "heyi": settings.heyi_base_url,
        "ollama": settings.ollama_base_url,
        "openai": "https://api.openai.com/v1",
    }
    return mapping.get(profile, "")


def _get_api_key(profile: str) -> str:
    import os
    mapping = {
        "yunwu": settings.yunwu_api_key,
        "heyi": settings.heyi_api_key,
        "ollama": settings.ollama_api_key,
        "openai": os.environ.get("OPENAI_API_KEY", ""),
    }
    return mapping.get(profile, "")


def _get_model(profile: str) -> str:
    mapping = {
        "yunwu": settings.yunwu_model,
        "heyi": settings.heyi_model,
        "ollama": settings.ollama_model,
        "openai": "gpt-4o-mini",
    }
    return mapping.get(profile, "")
