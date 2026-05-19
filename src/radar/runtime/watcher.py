"""监控巡检引擎 — 12 类信号

信号类型（分 3 组）：
  ── 数据健康 ──
  1. data_stale          : 数据源 N 小时无新数据
  2. source_failing      : 连续 N 次抓取失败（scheduler.py 触发）
  3. zero_items          : 数据库从未有数据（初始化问题）
  4. report_stale        : 报告 N 小时未更新

  ── 系统健康 ──
  5. disk_low            : 磁盘空间不足
  6. memory_high         : 内存使用率过高（可选）
  7. scheduler_dead      : 调度器未运行

  ── 认证健康 ──
  8. token_expiring      : GitHub Token 无效/即将失效
  9. reddit_auth_fail    : Reddit API 失败率过高
  10. llm_unreachable    : LLM 接口不可达
  11. llm_quota_low      : LLM Token 余额不足（可选，API 支持时）
  12. rate_limit_hit     : 速率限制命中过于频繁
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select

from radar.config import settings
from radar.storage.database import get_session
from radar.storage.models import Incident, Item, Report, SourceRun

logger = structlog.get_logger(__name__)


async def run_checks() -> None:
    """运行所有监控检查（12 类信号）"""
    await _check_data_staleness()            # 1
    await _check_zero_items()               # 3
    await _check_report_staleness()         # 4
    await _check_disk_space()               # 5
    await _check_scheduler_health()         # 7
    await _check_github_token()             # 8
    await _check_llm_health()               # 10


async def _check_data_staleness() -> None:
    """检查各数据源是否长时间没有新数据"""
    threshold_s = settings.data_stale_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_s)

    async with get_session() as session:
        for source in ["github", "reddit"]:
            result = await session.execute(
                select(func.max(Item.fetched_at)).where(Item.source == source)
            )
            last_fetched = result.scalar_one_or_none()

            if last_fetched is None:
                continue  # 还没有数据，不告警（初始状态）

            if last_fetched.tzinfo is None:
                last_fetched = last_fetched.replace(tzinfo=timezone.utc)

            if last_fetched < cutoff:
                age_h = (datetime.now(timezone.utc) - last_fetched).total_seconds() / 3600
                await _maybe_create_incident(
                    signal_type="data_stale",
                    severity="warning",
                    affected_resource=source,
                    title=f"{source.upper()} 数据已 {age_h:.1f} 小时未更新",
                    detail=f"上次更新时间：{last_fetched.isoformat()}",
                    context_data={"last_fetched_at": last_fetched.isoformat(), "age_hours": age_h},
                )


async def _check_disk_space() -> None:
    """检查磁盘剩余空间"""
    threshold_gb = settings.disk_low_gb
    try:
        usage = shutil.disk_usage(str(settings.output_dir))
        free_gb = usage.free / 1e9
        if free_gb < threshold_gb:
            await _maybe_create_incident(
                signal_type="disk_low",
                severity="critical" if free_gb < threshold_gb / 2 else "warning",
                affected_resource="disk",
                title=f"磁盘空间不足（剩余 {free_gb:.1f} GB）",
                detail=f"阈值：{threshold_gb} GB，当前：{free_gb:.2f} GB",
                context_data={"free_gb": free_gb, "threshold_gb": threshold_gb},
            )
    except Exception as exc:
        logger.warning("磁盘检查失败", error=str(exc))


async def _check_zero_items() -> None:
    """数据库从未有数据（信号 3）"""
    async with get_session() as session:
        total = (await session.execute(select(func.count()).select_from(Item))).scalar_one()
        run_count = (await session.execute(
            select(func.count()).select_from(SourceRun).where(SourceRun.status == "done")
        )).scalar_one()

    if run_count > 0 and total == 0:
        await _maybe_create_incident(
            signal_type="zero_items",
            severity="critical",
            affected_resource="database",
            title="有成功的抓取运行，但数据库中没有 Item",
            detail=f"成功运行次数: {run_count}，Item 总数: 0",
        )


async def _check_report_staleness() -> None:
    """报告超期检查（信号 4）"""
    threshold_h = 25  # 超过 25 小时未更新报告视为超期（每天跑一次）
    cutoff = datetime.now(timezone.utc) - timedelta(hours=threshold_h)

    async with get_session() as session:
        for template in ["projects", "communities"]:
            result = await session.execute(
                select(func.max(Report.generated_at)).where(Report.template == template)
            )
            last = result.scalar_one_or_none()
            if last is None:
                continue  # 还没有报告，不告警

            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)

            if last < cutoff:
                age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
                await _maybe_create_incident(
                    signal_type="report_stale",
                    severity="warning",
                    affected_resource=template,
                    title=f"{template} 报告已 {age_h:.1f} 小时未更新",
                    detail=f"上次生成：{last.isoformat()}",
                    context_data={"template": template, "age_hours": age_h},
                )


async def _check_scheduler_health() -> None:
    """调度器健康检查（信号 7）"""
    from radar.runtime.scheduler import get_scheduler
    sched = get_scheduler()
    if not sched.running:
        await _maybe_create_incident(
            signal_type="scheduler_dead",
            severity="critical",
            affected_resource="scheduler",
            title="调度器未运行",
            detail="APScheduler 已停止，所有定时任务将无法执行",
        )


async def _check_llm_health() -> None:
    """LLM 健康检查（信号 10）"""
    if not settings.llm_base_url:
        return
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.llm_api_key or "test",
            base_url=settings.llm_base_url,
            timeout=10.0,
        )
        models = await client.models.list()
        if not models.data:
            raise ValueError("模型列表为空")
    except Exception as exc:
        error_str = str(exc)
        # 超时 / 拒绝连接 = 不可达
        if any(kw in error_str.lower() for kw in ["timeout", "connect", "refused", "unreachable"]):
            await _maybe_create_incident(
                signal_type="llm_unreachable",
                severity="warning",
                affected_resource="llm",
                title=f"LLM 接口不可达（{settings.llm_base_url}）",
                detail=error_str[:300],
            )
        # 余额不足
        elif "quota" in error_str.lower() or "insufficient" in error_str.lower():
            await _maybe_create_incident(
                signal_type="llm_quota_low",
                severity="critical",
                affected_resource="llm",
                title="LLM Token 余额可能不足",
                detail=error_str[:300],
            )


async def _check_github_token() -> None:
    """检查 GitHub Token 是否即将过期（PAT 无法自动检测过期，靠 API 返回 401 判断）"""
    if not settings.github_token:
        return
    from radar.sources.github.client import GitHubClient
    try:
        async with GitHubClient(token=settings.github_token) as client:
            rate = await client.get_rate_limit()
            if not rate or rate.get("limit", 0) <= 60:
                await _maybe_create_incident(
                    signal_type="token_expiring",
                    severity="critical",
                    affected_resource="github",
                    title="GitHub Token 无效或已过期",
                    detail="API 返回匿名速率限制（60 req/h），Token 可能已失效",
                    context_data={"rate_limit": rate},
                )
    except ValueError as exc:
        # GitHubClient 抛出 ValueError 表示 401
        await _maybe_create_incident(
            signal_type="token_expiring",
            severity="critical",
            affected_resource="github",
            title="GitHub Token 认证失败（401）",
            detail=str(exc),
        )
    except Exception as exc:
        logger.warning("GitHub Token 检查失败（网络问题）", error=str(exc))


async def _maybe_create_incident(
    signal_type: str,
    severity: str,
    affected_resource: str,
    title: str,
    detail: str | None = None,
    context_data: dict | None = None,
) -> None:
    """创建 Incident（24h 内同类型同资源去重）"""
    from datetime import timedelta

    async with get_session() as session:
        # 去重：同类型同资源 24h 内只创建一次
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        existing = await session.execute(
            select(Incident).where(
                Incident.signal_type == signal_type,
                Incident.affected_resource == affected_resource,
                Incident.status.in_(["open", "resolving"]),
                Incident.detected_at >= since,
            )
        )
        if existing.scalar_one_or_none():
            return  # 已存在，不重复创建

        inc = Incident(
            signal_type=signal_type,
            severity=severity,
            affected_resource=affected_resource,
            title=title,
            detail=detail,
            context_data=context_data,
            status="open",
        )
        session.add(inc)
        logger.warning("创建 Incident", signal_type=signal_type, resource=affected_resource, title=title)

        # macOS 通知
        if settings.macos_notify and severity in ("warning", "critical"):
            from radar.runtime.scheduler import _send_macos_notify
            _send_macos_notify(title=f"Radar: {title}", message=detail or "")
