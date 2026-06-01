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

# 报告频率 → (cron 表达式, 数据窗口天数)
REPORT_FREQ_MAP: dict[str, tuple[str, int]] = {
    "daily":   ("0 6 * * *",   1),   # 每天 06:00，取最近 1 天数据
    "weekly":  ("0 6 * * 1",   7),   # 每周一 06:00，取最近 7 天数据
    "monthly": ("0 6 1 * *",  30),   # 每月 1 日 06:00，取最近 30 天数据
    "manual":  ("0 6 1 1 *",   0),   # 不自动执行（改为极小概率触发），手动触发全量
}


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
    # 报告调度
    report_projects_cron: str
    report_communities_cron: str
    report_projects_frequency: str   # daily/weekly/monthly/manual（从 cron 反推）
    report_communities_frequency: str
    report_projects_days_back: int   # 对应的数据窗口天数
    report_communities_days_back: int


class UpdateSourcesRequest(BaseModel):
    github_enabled: bool = True
    github_interval: str = "6h"
    reddit_enabled: bool = True
    reddit_interval: str = "1h"


class UpdateReportRequest(BaseModel):
    projects_frequency: Literal["daily", "weekly", "monthly", "manual"] = "daily"
    projects_hour: int = 6      # 几点触发（0-23）
    communities_frequency: Literal["daily", "weekly", "monthly", "manual"] = "daily"
    communities_hour: int = 6


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
        report_projects_frequency=_cron_to_freq(settings.report_projects_cron),
        report_communities_frequency=_cron_to_freq(settings.report_communities_cron),
        report_projects_days_back=REPORT_FREQ_MAP.get(_cron_to_freq(settings.report_projects_cron), ("", 0))[1],
        report_communities_days_back=REPORT_FREQ_MAP.get(_cron_to_freq(settings.report_communities_cron), ("", 0))[1],
    )


def _cron_to_freq(cron: str) -> str:
    """从 cron 表达式反推频率标签"""
    reverse = {v[0]: k for k, v in REPORT_FREQ_MAP.items()}
    # 忽略小时部分差异，只匹配模式
    normalized = cron.strip()
    if normalized == "0 6 * * *" or normalized.startswith("0 ") and normalized.endswith("* * *"):
        return "daily"
    if normalized.endswith("* * 1") or "* * 1" in normalized:
        return "weekly"
    if "1 * *" in normalized and normalized.count("*") >= 2:
        return "monthly"
    return reverse.get(normalized, "daily")


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


# ── 报告配置 ──────────────────────────────────────────────────────────────────


@router.get("/report", summary="获取当前报告调度配置")
async def get_report_config() -> dict:
    return {
        "projects_frequency": _cron_to_freq(settings.report_projects_cron),
        "projects_cron": settings.report_projects_cron,
        "projects_days_back": REPORT_FREQ_MAP.get(_cron_to_freq(settings.report_projects_cron), ("", 0))[1],
        "communities_frequency": _cron_to_freq(settings.report_communities_cron),
        "communities_cron": settings.report_communities_cron,
        "communities_days_back": REPORT_FREQ_MAP.get(_cron_to_freq(settings.report_communities_cron), ("", 0))[1],
    }


@router.post("/report", summary="更新报告调度配置（写入 .env + 热更新调度器）")
async def update_report_config(req: UpdateReportRequest) -> dict:
    if req.projects_frequency not in REPORT_FREQ_MAP:
        return {"ok": False, "message": f"无效频率: {req.projects_frequency}"}

    def _make_cron(freq: str, hour: int) -> str:
        base, _ = REPORT_FREQ_MAP[freq]
        # 替换小时部分
        parts = base.split()
        parts[1] = str(max(0, min(23, hour)))
        return " ".join(parts)

    proj_cron = _make_cron(req.projects_frequency, req.projects_hour)
    comm_cron = _make_cron(req.communities_frequency, req.communities_hour)

    _patch_env({
        "REPORT_PROJECTS_CRON": proj_cron,
        "REPORT_COMMUNITIES_CRON": comm_cron,
    })

    # 热更新调度器（无需重启服务）
    try:
        from radar.runtime.scheduler import reschedule_reports
        await reschedule_reports(proj_cron, comm_cron)
        hot_update = True
    except Exception as exc:
        logger.warning("调度器热更新失败，重启后生效: %s", exc)
        hot_update = False

    msg = "报告调度已更新" + ("（已热更新，无需重启）" if hot_update else "（写入 .env，重启后生效）")
    return {"ok": True, "message": msg, "projects_cron": proj_cron, "communities_cron": comm_cron}


@router.post("/report/trigger/{template}", summary="立即生成一次报告")
async def trigger_report_now(template: str) -> dict:
    """手动立即触发一次报告生成（使用当前频率对应的数据窗口）"""
    if template not in ("projects", "communities"):
        return {"ok": False, "message": "template 只能是 projects 或 communities"}

    freq = _cron_to_freq(
        settings.report_projects_cron if template == "projects" else settings.report_communities_cron
    )
    days_back = REPORT_FREQ_MAP.get(freq, ("", 0))[1]

    try:
        if template == "projects":
            from radar.outputs.projects import render_projects_report
            result = await render_projects_report(days_back=days_back)
        else:
            from radar.outputs.communities import render_communities_report
            result = await render_communities_report(days_back=days_back)
        return {"ok": True, "message": f"报告已生成", **result}
    except ImportError:
        # Editable-install 边缘情况：outputs 子包路径未被 venv 收录。
        # Fallback 用 asyncio subprocess 调 CLI render 命令。
        import asyncio, sys
        cmd = [sys.executable, "-m", "radar.cli", "render", template,
               "--days-back", str(days_back)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0:
                return {"ok": True, "message": "报告已生成（CLI fallback）",
                        "stdout": stdout.decode()[-500:]}
            return {"ok": False, "message": f"CLI fallback 失败: {stderr.decode()[-300:]}"}
        except Exception as exc2:
            return {"ok": False, "message": f"CLI fallback 异常: {exc2}"}
    except Exception as exc:
        logger.exception("手动触发报告失败")
        return {"ok": False, "message": str(exc)}


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
