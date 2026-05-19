"""监控巡检（S8 完整实现前的骨架）

当前实现：
- 数据新鲜度检查（source_stale）
- 磁盘空间检查（disk_low）
- Token 过期检查（token_expiring）
- 爬取失败检查（source_failing，scheduler.py 中触发）

S8 完整版将覆盖 12 类信号。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select

from radar.config import settings
from radar.storage.database import get_session
from radar.storage.models import Incident, Item, SourceRun

logger = structlog.get_logger(__name__)


async def run_checks() -> None:
    """运行所有监控检查"""
    await _check_data_staleness()
    await _check_disk_space()
    await _check_github_token()


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
