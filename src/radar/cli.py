"""Radar CLI 入口"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(name="radar", help="AI 需求抓取 · 趋势分析平台", no_args_is_help=True)


# ── 系统管理 ──────────────────────────────────────────────────────────────


@app.command("serve", help="启动 Web 服务")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-H"),
    port: int = typer.Option(None, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    from radar.config import settings
    from radar.app import create_app

    _port = port or settings.web_port
    console.print(f"[bold green]🚀 Radar 启动中[/] → http://localhost:{_port}")
    uvicorn.run(
        "radar.app:create_app",
        factory=True,
        host=host,
        port=_port,
        reload=reload,
        log_level="info",
    )


@app.command("init", help="初始化数据库（建表）")
def init_db_cmd() -> None:
    from radar.storage.database import init_db

    async def _run() -> None:
        await init_db()
        console.print("[green]✓[/] 数据库初始化完成")

    asyncio.run(_run())


# ── 数据源管理 ────────────────────────────────────────────────────────────


@app.command("status", help="查看各数据源当前状态")
def status_cmd() -> None:
    from radar.storage.database import init_db, get_session
    from radar.storage.models import SourceRun, Item
    from sqlalchemy import func, select

    async def _run() -> None:
        await init_db()
        async with get_session() as session:
            counts = await session.execute(
                select(Item.source, func.count(Item.id).label("cnt")).group_by(Item.source)
            )
            count_map = {r.source: r.cnt for r in counts}

            runs = await session.execute(
                select(SourceRun).order_by(SourceRun.created_at.desc()).limit(20)
            )
            run_rows = list(runs.scalars())

        t = Table(title="数据源状态", show_lines=True)
        t.add_column("源", style="cyan")
        t.add_column("总条目", justify="right")
        t.add_column("最近状态", justify="center")
        t.add_column("本次获取", justify="right")
        t.add_column("本次新增", justify="right")
        t.add_column("时间")

        seen: set[str] = set()
        for run in run_rows:
            if run.source in seen:
                continue
            seen.add(run.source)
            status_color = {
                "done": "[green]done[/]",
                "failed": "[red]failed[/]",
                "running": "[yellow]running[/]",
            }.get(run.status, run.status)
            t.add_row(
                run.source,
                str(count_map.get(run.source, 0)),
                status_color,
                str(run.items_in),
                str(run.items_new),
                run.created_at.strftime("%m-%d %H:%M") if run.created_at else "-",
            )

        for src, cnt in count_map.items():
            if src not in seen:
                t.add_row(src, str(cnt), "-", "-", "-", "-")

        console.print(t)

    asyncio.run(_run())


@app.command("crawl", help="手动触发一次抓取（source: github / reddit / all）")
def crawl_cmd(
    source: str = typer.Argument("all", help="数据源名称，all=所有"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印要执行的操作，不实际抓取"),
) -> None:
    """手动触发抓取（S2/S3 实现后生效）"""
    from radar.runtime.crawler import run_crawl  # S2/S3 实现

    async def _run() -> None:
        await run_crawl(source=source, dry_run=dry_run)

    asyncio.run(_run())


# ── Incident 管理 ─────────────────────────────────────────────────────────


@app.command("incidents", help="查看未解决的 Incident 列表")
def incidents_cmd(
    all_status: bool = typer.Option(False, "--all", "-a", help="显示所有状态（含已解决）"),
) -> None:
    from radar.storage.database import init_db, get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    async def _run() -> None:
        await init_db()
        async with get_session() as session:
            q = select(Incident).order_by(Incident.detected_at.desc()).limit(50)
            if not all_status:
                q = q.where(Incident.status == "open")
            result = await session.execute(q)
            incidents = list(result.scalars())

        if not incidents:
            console.print("[green]✓[/] 没有未解决的 Incident")
            return

        t = Table(title="Incident 列表", show_lines=True)
        t.add_column("ID", style="dim", width=8)
        t.add_column("严重度")
        t.add_column("类型")
        t.add_column("标题")
        t.add_column("状态")
        t.add_column("发现时间")

        severity_color = {"critical": "red", "warning": "yellow", "info": "blue"}
        for inc in incidents:
            color = severity_color.get(inc.severity, "white")
            t.add_row(
                inc.id[:8],
                f"[{color}]{inc.severity}[/]",
                inc.signal_type,
                inc.title[:60],
                inc.status,
                inc.detected_at.strftime("%m-%d %H:%M"),
            )
        console.print(t)

    asyncio.run(_run())


# ── 报告 ──────────────────────────────────────────────────────────────────


@app.command("reports", help="查看已生成的报告")
def reports_cmd(
    template: str = typer.Option(None, "--template", "-t", help="过滤模板类型"),
) -> None:
    from radar.storage.database import init_db, get_session
    from radar.storage.models import Report
    from sqlalchemy import select

    async def _run() -> None:
        await init_db()
        async with get_session() as session:
            q = select(Report).order_by(Report.generated_at.desc()).limit(20)
            if template:
                q = q.where(Report.template == template)
            result = await session.execute(q)
            reports = list(result.scalars())

        if not reports:
            console.print("[yellow]暂无报告，等待 cron 首次渲染[/]")
            return

        t = Table(title="报告列表", show_lines=True)
        t.add_column("模板")
        t.add_column("周期")
        t.add_column("条目数", justify="right")
        t.add_column("状态")
        t.add_column("生成时间")
        t.add_column("文件路径")

        for r in reports:
            status_color = "[green]ok[/]" if r.status == "ok" else f"[red]{r.status}[/]"
            t.add_row(
                r.template,
                r.period_key,
                str(r.item_count),
                status_color,
                r.generated_at.strftime("%m-%d %H:%M"),
                r.file_path or "-",
            )
        console.print(t)

    asyncio.run(_run())


@app.command("render", help="立即生成一次报告（projects / communities / all）")
def render_cmd(
    template: str = typer.Argument("all", help="projects / communities / all"),
    days_back: int = typer.Option(0, "--days-back", "-d", help="仅包含最近 N 天数据，0=全量"),
) -> None:
    """强制渲染一次 HTML 报告并保存到 outputs/。

    常用场景：首次部署后手动触发，不等 cron 计划。
    """
    from radar.storage.database import init_db

    async def _run() -> None:
        await init_db()
        templates = ["projects", "communities"] if template == "all" else [template]
        for t in templates:
            console.print(f"[cyan]正在渲染 {t} 报告…[/]")
            try:
                if t == "projects":
                    from radar.outputs.projects import render_projects_report
                    result = await render_projects_report(days_back=days_back)
                else:
                    from radar.outputs.communities import render_communities_report
                    result = await render_communities_report(days_back=days_back)
                console.print(f"[green]✓ {t} 报告渲染完成[/]", result)
            except Exception as exc:
                console.print(f"[red]✗ {t} 报告渲染失败：{exc}[/]")

    asyncio.run(_run())


# ── Token 管理 ────────────────────────────────────────────────────────────


@app.command("score", help="手动触发 LLM 评分")
def score_cmd(
    source: str = typer.Option(None, "--source", "-s", help="过滤数据源"),
    limit: int = typer.Option(50, "--limit", "-n", help="最多评分条数"),
    force: bool = typer.Option(False, "--force", help="强制重新评分（覆盖已有评分）"),
) -> None:
    from radar.storage.database import init_db
    from radar.analyzer.scorer import score_unscored_items

    async def _run() -> None:
        await init_db()
        result = await score_unscored_items(source=source, limit=limit, force=force)
        console.print(
            f"[green]✓[/] 评分完成：成功 {result['scored']} 条，失败 {result['failed']} 条"
        )

    asyncio.run(_run())


@app.command("token", help="交互式 Token 管理向导")
def token_cmd(
    source: str = typer.Argument(..., help="数据源名称（github / reddit）"),
    action: str = typer.Option("status", "--action", "-a", help="status / refresh / wizard"),
) -> None:
    """Token 管理（S2/S3 实现后生效）"""
    from radar.auth.wizard import run_wizard  # S2/S3 实现

    async def _run() -> None:
        await run_wizard(source=source, action=action)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
