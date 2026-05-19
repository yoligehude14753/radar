"""项目分类报告渲染（模板 A）

从 radar DB 读取：
- Item（来源：github）
- Score（evaluator=qag，包含 pain/market/feasibility/velocity）
- Tag（namespace=domain，领域分类）

生成 HTML 报告，风格对齐 agent-radar/report_latest.html。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from radar.analyzer.domain_meta import DOMAIN_META
from radar.config import settings
from radar.storage.database import get_session
from radar.storage.models import Item, Report, Score, Tag

logger = structlog.get_logger(__name__)


async def render_projects_report(days_back: int = 0) -> dict:
    """渲染项目分类报告，保存 HTML + Report 记录，返回 {status, path}。

    Args:
        days_back: 仅包含最近 N 天内抓取的数据；0 表示不限制（全量）。
    """
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 DB 读取数据
    domains_data = await _load_domain_data(days_back=days_back)

    # 生成 HTML
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = _render_html(domains_data, generated_at)

    # 写文件
    filename = f"projects_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.html"
    file_path = output_dir / filename
    file_path.write_text(html, encoding="utf-8")

    # 写 latest 软链（方便 API 获取最新）
    latest_path = output_dir / "projects_latest.html"
    latest_path.write_text(html, encoding="utf-8")

    # 保存 Report 记录（upsert：同一 period_key 覆盖旧记录）
    total_items = sum(len(d["items"]) for d in domains_data)
    pk = _period_key(days_back)
    async with get_session() as session:
        existing = await session.execute(
            select(Report).where(Report.template == "projects", Report.period_key == pk)
        )
        old = existing.scalar_one_or_none()
        if old is not None:
            await session.delete(old)
            await session.flush()
        report = Report(
            template="projects",
            period_key=pk,
            file_path=str(file_path),
            item_count=total_items,
            status="ok",
            params={
                "domains": len(domains_data),
                "generated_at": generated_at,
                "days_back": days_back,
                "file_size": file_path.stat().st_size,
            },
        )
        session.add(report)

    logger.info("projects 报告渲染完成", file=filename, items=total_items)
    return {"status": "ok", "file": filename, "items": total_items}


def _period_key(days_back: int) -> str:
    """根据 days_back 生成 period_key，表示本次报告的时间维度。"""
    from datetime import date
    today = date.today()
    if days_back == 0:
        return today.isoformat()           # 全量：2026-05-19
    if days_back <= 1:
        return today.isoformat()           # 日频
    if days_back <= 7:
        # 周频：2026-W21
        return f"{today.year}-W{today.isocalendar().week:02d}"
    if days_back <= 31:
        # 月频：2026-05
        return f"{today.year}-{today.month:02d}"
    return today.isoformat()


async def _load_domain_data(days_back: int = 0) -> list[dict]:
    """从 DB 加载按领域分组的项目数据。
    
    days_back > 0 时只包含最近 days_back 天抓取的 Item。
    """
    from datetime import timedelta
    since_dt: Optional[datetime] = None
    if days_back > 0:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days_back)

    domains_data: list[dict] = []

    async with get_session() as session:
        for domain_id, meta in DOMAIN_META.items():
            # 找属于该领域的 Item（通过 Tag）
            q = (
                select(Item)
                .join(Tag, (Tag.item_id == Item.id) & (Tag.namespace == "domain") & (Tag.value == domain_id))
                .where(Item.source == "github")
                .order_by(Item.fetched_at.desc())
                .limit(20)
            )
            if since_dt is not None:
                q = q.where(Item.fetched_at >= since_dt)
            result = await session.execute(q)
            items = result.scalars().all()

            if not items:
                continue

            # 获取每个 item 的 QAG 评分
            item_list = []
            for item in items:
                score_result = await session.execute(
                    select(Score)
                    .where(Score.item_id == item.id, Score.evaluator == "qag")
                    .order_by(Score.created_at.desc())
                    .limit(1)
                )
                score = score_result.scalar_one_or_none()
                platform_data = item.platform_data or {}
                item_list.append({
                    "full_name": item.external_id or item.title,
                    "url": item.url,
                    "description": item.content or "",
                    "stars": platform_data.get("stars", 0),
                    "language": platform_data.get("language", ""),
                    "topics": platform_data.get("topics", []),
                    "score": round(score.score, 3) if score else None,
                    "pain": score.dimensions.get("pain", 0) if score else 0,
                    "market": score.dimensions.get("market", 0) if score else 0,
                    "reason": score.dimensions.get("reason", "") if score else "",
                })

            item_list.sort(key=lambda x: (x.get("score") or 0, x.get("stars", 0)), reverse=True)
            domains_data.append({
                "domain_id": domain_id,
                "meta": meta,
                "items": item_list,
            })

    domains_data.sort(key=lambda d: len(d["items"]), reverse=True)
    return domains_data


def _render_html(domains_data: list[dict], generated_at: str) -> str:
    total_items = sum(len(d["items"]) for d in domains_data)
    total_domains = len(domains_data)

    # 渲染各领域的 HTML
    domain_sections = "".join(_render_domain_section(d) for d in domains_data)

    if not domain_sections:
        domain_sections = '<div class="empty">暂无数据，请先运行 <code>radar crawl github</code> 并完成评分</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Radar · AI 项目趋势分类</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{font-size:14px}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.5}}
a{{color:#58a6ff;text-decoration:none}}a:hover{{text-decoration:underline}}
.page{{max-width:1200px;margin:0 auto;padding:20px 16px}}
.header{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;margin-bottom:20px}}
.header h1{{font-size:1.4rem;font-weight:700;margin-bottom:8px}}
.header-meta{{font-size:.82rem;color:#8b949e}}
.stats{{display:flex;gap:16px;margin-top:12px;flex-wrap:wrap}}
.stat-item{{background:#21262d;border-radius:8px;padding:8px 16px;font-size:.85rem}}
.stat-num{{font-size:1.2rem;font-weight:700;color:#58a6ff;display:block}}
.domain-section{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin-bottom:16px}}
.domain-header{{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}}
.domain-name{{font-size:1.05rem;font-weight:700;color:#e6edf3}}
.domain-verdict{{font-size:.72rem;background:#21262d;border:1px solid #30363d;
  border-radius:4px;padding:2px 8px;color:#8b949e}}
.domain-sub{{font-size:.8rem;color:#8b949e;margin-bottom:12px}}
.item-list{{display:flex;flex-direction:column;gap:8px}}
.item-card{{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px 16px}}
.item-card:hover{{border-color:#444c56}}
.item-header{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}}
.item-name{{font-weight:600;color:#58a6ff}}
.badge{{background:#21262d;border:1px solid #30363d;border-radius:4px;
  padding:1px 6px;font-size:.72rem;color:#8b949e}}
.score-bar{{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}}
.score-dim{{font-size:.75rem;color:#8b949e}}
.score-dim span{{color:#e6edf3;font-weight:600}}
.item-desc{{font-size:.82rem;color:#8b949e;margin-top:4px;line-height:1.5}}
.item-reason{{font-size:.78rem;color:#8b949e;margin-top:4px;font-style:italic}}
.empty{{text-align:center;padding:40px;color:#8b949e}}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <h1>🛰️ Radar · AI 项目趋势分类</h1>
    <div class="header-meta">更新时间：{generated_at}</div>
    <div class="stats">
      <div class="stat-item"><span class="stat-num">{total_items:,}</span>项目</div>
      <div class="stat-item"><span class="stat-num">{total_domains}</span>活跃领域</div>
    </div>
  </div>

  {domain_sections}
</div>
</body>
</html>"""


def _render_domain_section(d: dict) -> str:
    meta = d["meta"]
    items = d["items"]
    if not items:
        return ""

    items_html = "".join(_render_item_card(item) for item in items[:10])
    return f"""
<div class="domain-section">
  <div class="domain-header">
    <div class="domain-name">{meta.get('name', d['domain_id'])}</div>
    <div class="domain-verdict">{meta.get('verdictLabel', '')}</div>
  </div>
  <div class="domain-sub">{meta.get('sub', '')}</div>
  <div class="item-list">
    {items_html}
  </div>
</div>"""


def _render_item_card(item: dict) -> str:
    name = item.get("full_name", "")
    url = item.get("url", "#")
    desc = (item.get("description") or "")[:200]
    stars = item.get("stars", 0)
    lang = item.get("language", "")
    score = item.get("score")
    pain = item.get("pain", 0)
    market = item.get("market", 0)
    reason = item.get("reason", "")

    stars_str = f"{stars/1000:.1f}k" if stars >= 1000 else str(stars)
    score_html = ""
    if score is not None:
        score_pct = round(score * 100)
        score_html = f"""
    <div class="score-bar">
      <div class="score-dim">综合 <span>{score_pct}</span></div>
      <div class="score-dim">痛点 <span>{round(pain*100)}</span></div>
      <div class="score-dim">市场 <span>{round(market*100)}</span></div>
    </div>"""

    reason_html = f'<div class="item-reason">💡 {_esc(reason)}</div>' if reason else ""

    return f"""
<div class="item-card">
  <div class="item-header">
    <a class="item-name" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(name)}</a>
    <span class="badge">⭐ {stars_str}</span>
    {f'<span class="badge">{_esc(lang)}</span>' if lang else ""}
  </div>
  {f'<div class="item-desc">{_esc(desc)}</div>' if desc else ""}
  {score_html}
  {reason_html}
</div>"""


def _esc(s: str) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
