"""APScheduler 任务调度器

负责：
- GitHub / Reddit 定时抓取（cron 配置）
- 报告模板定时渲染（cron 配置）
- 监控 watcher 定时巡检（每 5 分钟）
- 启动/停止生命周期管理
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = structlog.get_logger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


async def start_scheduler() -> None:
    """启动调度器，注册所有任务"""
    from radar.config import settings

    sched = get_scheduler()
    if sched.running:
        logger.warning("调度器已在运行，跳过重复启动")
        return

    # ── GitHub 抓取 ──────────────────────────────────────────────────────
    github_interval_s = settings.interval_seconds(settings.github_crawl_interval)
    sched.add_job(
        _run_github_crawl,
        trigger=IntervalTrigger(seconds=github_interval_s),
        id="github_crawl",
        name="GitHub 增量抓取",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("注册 GitHub 抓取任务", interval_s=github_interval_s)

    # ── Reddit 抓取 ──────────────────────────────────────────────────────
    reddit_interval_s = settings.interval_seconds(settings.reddit_crawl_interval)
    sched.add_job(
        _run_reddit_crawl,
        trigger=IntervalTrigger(seconds=reddit_interval_s),
        id="reddit_crawl",
        name="Reddit 增量抓取",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("注册 Reddit 抓取任务", interval_s=reddit_interval_s)

    # ── Projects 报告渲染（每天 06:00）────────────────────────────────────
    sched.add_job(
        _run_render_projects,
        trigger=CronTrigger.from_crontab(settings.report_projects_cron),
        id="render_projects",
        name="渲染项目分类报告",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("注册 projects 报告任务", cron=settings.report_projects_cron)

    # ── Communities 报告渲染（每天 06:00）────────────────────────────────
    sched.add_job(
        _run_render_communities,
        trigger=CronTrigger.from_crontab(settings.report_communities_cron),
        id="render_communities",
        name="渲染社群地图报告",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("注册 communities 报告任务", cron=settings.report_communities_cron)

    # ── 自动评分（每 30 分钟）────────────────────────────────────────────
    sched.add_job(
        _run_score_items,
        trigger=IntervalTrigger(minutes=30),
        id="score_items",
        name="自动评分",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("注册自动评分任务（每 30 分钟）")

    # ── 监控巡检（每 5 分钟）────────────────────────────────────────────
    sched.add_job(
        _run_watcher,
        trigger=IntervalTrigger(minutes=5),
        id="watcher",
        name="监控巡检",
        replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info("注册监控巡检任务（每 5 分钟）")

    sched.start()
    logger.info("调度器启动成功", job_count=len(sched.get_jobs()))


async def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("调度器已停止")


# ── 任务执行函数（带 circuit breaker 保护）──────────────────────────────────


async def _run_github_crawl() -> None:
    """带错误隔离的 GitHub 抓取"""
    try:
        from radar.sources.github.crawler import crawl_github
        result = await crawl_github()
        logger.info("GitHub 定时抓取完成", **result)
    except Exception as exc:
        logger.exception("GitHub 定时抓取异常", error=str(exc))
        await _record_crawl_incident("github", str(exc))


async def _run_reddit_crawl() -> None:
    """带错误隔离的 Reddit 抓取"""
    try:
        from radar.sources.reddit.crawler import crawl_reddit
        result = await crawl_reddit()
        logger.info("Reddit 定时抓取完成", **result)
    except Exception as exc:
        logger.exception("Reddit 定时抓取异常", error=str(exc))
        await _record_crawl_incident("reddit", str(exc))


async def _run_render_projects() -> None:
    """渲染 projects 报告（S6 实现后完整版）"""
    try:
        from radar.outputs.renderer import render_report
        result = await render_report("projects")
        logger.info("projects 报告渲染完成", **result)
    except Exception as exc:
        logger.exception("projects 报告渲染失败", error=str(exc))


async def _run_render_communities() -> None:
    """渲染 communities 报告（S7 实现后完整版）"""
    try:
        from radar.outputs.renderer import render_report
        result = await render_report("communities")
        logger.info("communities 报告渲染完成", **result)
    except Exception as exc:
        logger.exception("communities 报告渲染失败", error=str(exc))


async def _run_score_items() -> None:
    """自动评分未评分 Item"""
    try:
        from radar.analyzer.scorer import score_unscored_items
        result = await score_unscored_items(limit=50)
        logger.info("自动评分完成", **result)
    except Exception as exc:
        logger.exception("自动评分异常", error=str(exc))


async def _run_watcher() -> None:
    """监控巡检（S8 实现后完整版）"""
    try:
        from radar.runtime.watcher import run_checks
        await run_checks()
    except Exception as exc:
        logger.exception("监控巡检异常", error=str(exc))


# ── Incident 辅助 ────────────────────────────────────────────────────────


async def _record_crawl_incident(source: str, error: str) -> None:
    """抓取连续失败时创建 Incident"""
    from datetime import datetime, timezone
    from radar.storage.database import get_session
    from radar.storage.models import Incident, IncidentAction, SourceRun
    from sqlalchemy import select, func

    try:
        async with get_session() as session:
            # 统计最近 N 次运行失败数
            from radar.config import settings
            threshold = settings.source_fail_threshold
            recent_runs = await session.execute(
                select(SourceRun.status)
                .where(SourceRun.source == source)
                .order_by(SourceRun.created_at.desc())
                .limit(threshold)
            )
            statuses = [r.status for r in recent_runs]
            fail_count = sum(1 for s in statuses if s == "failed")

            if fail_count < threshold:
                return  # 没达到告警阈值

            # 检查是否已有 open 的同类 Incident
            existing = await session.execute(
                select(Incident).where(
                    Incident.signal_type == "source_failing",
                    Incident.affected_resource == source,
                    Incident.status == "open",
                )
            )
            if existing.scalar_one_or_none():
                return  # 已有告警，不重复创建

            # 创建新 Incident
            inc = Incident(
                signal_type="source_failing",
                severity="critical",
                affected_resource=source,
                title=f"{source.upper()} 连续 {fail_count} 次抓取失败",
                detail=f"最近错误：{error[:500]}",
                context_data={"fail_count": fail_count, "threshold": threshold},
                status="open",
            )
            session.add(inc)
            await session.flush()

            # 添加修复动作
            session.add(IncidentAction(
                incident_id=inc.id,
                action_key="retry_source",
                label=f"立即重试 {source.upper()} 抓取",
                endpoint=f"/api/incidents/{inc.id}/actions/retry_source",
                order=0,
            ))
            session.add(IncidentAction(
                incident_id=inc.id,
                action_key="refresh_token",
                label="重新配置认证凭证",
                endpoint=f"/api/incidents/{inc.id}/actions/refresh_token",
                order=1,
            ))

            logger.warning("已创建 Incident", source=source, fail_count=fail_count)

            # macOS 通知
            from radar.config import settings as s
            if s.macos_notify:
                _send_macos_notify(
                    title=f"Radar: {source.upper()} 抓取失败",
                    message=f"连续 {fail_count} 次失败，请检查",
                )
    except Exception as exc:
        logger.error("记录 Incident 失败", error=str(exc))


def _send_macos_notify(title: str, message: str) -> None:
    """发送 macOS 系统通知（非阻塞）"""
    import subprocess
    try:
        subprocess.Popen(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}" sound name "Basso"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
