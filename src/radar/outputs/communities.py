"""社群地图报告渲染（模板 B）

从 radar DB 读取：
- Item（来源：reddit + github）
- 平台数据（subreddit / community links）

生成 HTML 报告，风格对齐 render_community_report_usecase.py。
包含平台过滤器（Reddit / GitHub），可搜索，分页展示。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy import select, func

from radar.config import settings
from radar.storage.database import get_session
from radar.storage.models import Item, Report

logger = structlog.get_logger(__name__)

_PLATFORM_META = {
    "reddit":  {"color": "#FF4500", "icon": "🤖", "label": "Reddit"},
    "github":  {"color": "#58a6ff", "icon": "⭐", "label": "GitHub"},
    "discord": {"color": "#5865F2", "icon": "💬", "label": "Discord"},
    "telegram": {"color": "#26A5E4", "icon": "✈️", "label": "Telegram"},
    "wechat":  {"color": "#07C160", "icon": "💚", "label": "微信"},
}


async def render_communities_report(days_back: int = 0) -> dict:
    """渲染社群地图报告，保存 HTML + Report 记录。

    Args:
        days_back: 仅包含最近 N 天内抓取的数据；0 表示不限制（全量）。
    """
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 DB 读取数据
    repos_data = await _load_community_data(days_back=days_back)

    # 生成 HTML
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_repos = len(repos_data)
    total_items = sum(len(r.get("items", [])) for r in repos_data)

    # 写数据 JSON（异步加载）
    data_filename = f"communities_data_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
    data_path = output_dir / data_filename
    latest_data_path = output_dir / "communities_data_latest.json"
    data_json = json.dumps(repos_data, ensure_ascii=False, separators=(",", ":"))
    data_path.write_text(data_json, encoding="utf-8")
    latest_data_path.write_text(data_json, encoding="utf-8")

    # 统计各平台数量
    stats: dict[str, int] = {}
    for r in repos_data:
        for item in r.get("items", []):
            plat = item.get("platform", "")
            if plat:
                stats[plat] = stats.get(plat, 0) + 1

    stats_html = "".join(
        f'<span class="stat-chip" style="--c:{_PLATFORM_META.get(k, {}).get("color", "#888")}">'
        f'{_PLATFORM_META.get(k, {}).get("icon", "🔗")} <strong>{v}</strong>'
        f' {_PLATFORM_META.get(k, {}).get("label", k)}</span>'
        for k, v in sorted(stats.items(), key=lambda x: -x[1])
    )

    platform_meta_json = json.dumps(_PLATFORM_META, ensure_ascii=False)
    html = _build_html(
        total_repos=total_repos,
        total_items=total_items,
        stats_html=stats_html,
        platform_meta_json=platform_meta_json,
        generated_at=generated_at,
        data_url=f"/outputs/communities_data_latest.json",
    )

    # 写文件
    filename = f"communities_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.html"
    file_path = output_dir / filename
    file_path.write_text(html, encoding="utf-8")
    (output_dir / "communities_latest.html").write_text(html, encoding="utf-8")

    # 保存 Report 记录（upsert：同一 period_key 覆盖旧记录）
    from sqlalchemy import select as _select
    pk = _period_key(days_back)
    async with get_session() as session:
        existing = await session.execute(
            _select(Report).where(Report.template == "communities", Report.period_key == pk)
        )
        old = existing.scalar_one_or_none()
        if old is not None:
            await session.delete(old)
            await session.flush()
        report = Report(
            template="communities",
            period_key=pk,
            file_path=str(file_path),
            item_count=total_repos,
            status="ok",
            params={
                "total_items": total_items,
                "generated_at": generated_at,
                "days_back": days_back,
                "file_size": file_path.stat().st_size,
                "data_file": str(data_path),
            },
        )
        session.add(report)

    logger.info("communities 报告渲染完成", file=filename, repos=total_repos)
    return {"status": "ok", "file": filename, "repos": total_repos, "items": total_items}


def _period_key(days_back: int) -> str:
    from datetime import date
    today = date.today()
    if days_back == 0 or days_back <= 1:
        return today.isoformat()
    if days_back <= 7:
        return f"{today.year}-W{today.isocalendar().week:02d}"
    if days_back <= 31:
        return f"{today.year}-{today.month:02d}"
    return today.isoformat()


async def _load_community_data(days_back: int = 0) -> list[dict]:
    """读取有社群入口的项目（Reddit 帖子 + GitHub 仓库）"""
    from datetime import timedelta, timezone
    since_dt = None
    if days_back > 0:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days_back)

    repos_data: list[dict] = []

    async with get_session() as session:
        # GitHub items（有社区 topics 的）
        gh_q = select(Item).where(Item.source == "github").order_by(Item.fetched_at.desc()).limit(200)
        if since_dt is not None:
            gh_q = gh_q.where(Item.fetched_at >= since_dt)
        gh_result = await session.execute(gh_q)
        for item in gh_result.scalars():
            pd = item.platform_data or {}
            topics = pd.get("topics", [])
            # 过滤出有社区相关特征的
            community_keywords = {"community", "discord", "telegram", "slack", "forum", "group", "chat"}
            has_community = any(kw in " ".join(topics).lower() for kw in community_keywords)
            # 没有社区关键词但 star > 500 的也展示
            if not has_community and pd.get("stars", 0) < 500:
                continue

            repos_data.append({
                "name": item.external_id or item.title,
                "url": item.url,
                "stars": pd.get("stars", 0),
                "lang": pd.get("language", ""),
                "desc": (item.content or "")[:300],
                "platforms": ["github"],
                "items": [{
                    "platform": "github",
                    "url": item.url,
                    "note": f"⭐ {pd.get('stars', 0)} | {pd.get('language', '')}",
                }],
            })

        # Reddit items
        rd_q = select(Item).where(Item.source == "reddit").order_by(Item.fetched_at.desc()).limit(200)
        if since_dt is not None:
            rd_q = rd_q.where(Item.fetched_at >= since_dt)
        reddit_result = await session.execute(rd_q)
        for item in reddit_result.scalars():
            pd = item.platform_data or {}
            subreddit = pd.get("subreddit", "")
            repos_data.append({
                "name": item.title[:80],
                "url": item.url,
                "stars": pd.get("ups", 0),
                "lang": subreddit,
                "desc": (item.content or "")[:200],
                "platforms": ["reddit"],
                "items": [{
                    "platform": "reddit",
                    "url": item.url,
                    "note": f"r/{subreddit} | ⬆ {pd.get('ups', 0)} | 💬 {pd.get('num_comments', 0)}",
                }],
            })

    # 按 stars/ups 降序
    repos_data.sort(key=lambda r: r.get("stars", 0), reverse=True)
    return repos_data


def _build_html(
    total_repos: int,
    total_items: int,
    stats_html: str,
    platform_meta_json: str,
    generated_at: str,
    data_url: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Radar · AI 社群地图</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{font-size:14px}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.5}}
a{{color:#58a6ff;text-decoration:none}}a:hover{{text-decoration:underline}}
.page{{max-width:1200px;margin:0 auto;padding:16px}}
.header{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px 24px;margin-bottom:16px}}
.header-title{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.header-title h1{{font-size:1.2rem;font-weight:700}}
.header-sub{{font-size:.8rem;color:#8b949e;margin-bottom:12px}}
.stat-chips{{display:flex;flex-wrap:wrap;gap:6px}}
.stat-chip{{background:color-mix(in srgb,var(--c,#888) 15%,transparent);
  border:1px solid color-mix(in srgb,var(--c,#888) 35%,transparent);
  color:var(--c,#888);border-radius:20px;padding:3px 12px;font-size:.78rem}}
.controls{{background:#161b22;border:1px solid #30363d;border-radius:12px;
  padding:14px 20px;margin-bottom:12px;display:flex;flex-direction:column;gap:10px}}
.ctrl-row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.ctrl-label{{font-size:.8rem;color:#8b949e;white-space:nowrap;min-width:50px}}
.search-input{{flex:1;min-width:200px;background:#0d1117;border:1px solid #30363d;
  border-radius:8px;padding:7px 12px;color:#e6edf3;font-size:.85rem;outline:none}}
.search-input:focus{{border-color:#58a6ff}}
.filter-chips{{display:flex;flex-wrap:wrap;gap:5px}}
.chip{{background:transparent;border:1px solid #30363d;border-radius:20px;
  padding:3px 12px;color:#8b949e;font-size:.78rem;cursor:pointer;transition:all .15s}}
.chip:hover{{border-color:#58a6ff;color:#58a6ff}}
.chip.active{{background:#58a6ff;border-color:#58a6ff;color:#fff;font-weight:600}}
.plat-chip.active{{background:color-mix(in srgb,var(--pc,#58a6ff) 20%,transparent);
  border-color:var(--pc,#58a6ff);color:var(--pc,#58a6ff)}}
.result-bar{{display:flex;justify-content:space-between;align-items:center;
  padding:8px 4px;font-size:.82rem;color:#8b949e;margin-bottom:6px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;
  padding:16px 20px;margin-bottom:10px}}
.card:hover{{border-color:#444c56}}
.card-header{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:6px}}
.card-name{{font-size:1rem;font-weight:600;color:#58a6ff}}
.badge{{background:#21262d;border:1px solid #30363d;border-radius:4px;
  padding:2px 7px;font-size:.72rem;color:#8b949e}}
.card-desc{{font-size:.82rem;color:#8b949e;margin-bottom:10px;line-height:1.5}}
.items{{display:flex;flex-direction:column;gap:6px;margin-top:8px}}
.item{{display:flex;align-items:center;gap:10px;background:#0d1117;
  border:1px solid #30363d;border-radius:8px;padding:8px 14px}}
.item-plat{{display:flex;align-items:center;gap:5px;font-size:.78rem;font-weight:600;
  min-width:80px;color:var(--pc,#8b949e)}}
.item-link{{font-size:.82rem;flex:1;word-break:break-all}}
.item-note{{font-size:.78rem;color:#8b949e;margin-left:8px}}
.pagination{{display:flex;align-items:center;justify-content:center;gap:6px;
  padding:20px 0;flex-wrap:wrap}}
.pg-btn{{background:#161b22;border:1px solid #30363d;border-radius:6px;
  padding:5px 14px;color:#e6edf3;cursor:pointer;font-size:.82rem;transition:all .15s}}
.pg-btn:hover{{border-color:#58a6ff;color:#58a6ff}}
.pg-btn:disabled{{opacity:.4;cursor:default}}
.pg-info{{font-size:.82rem;color:#8b949e}}
.empty{{text-align:center;padding:40px;color:#8b949e}}
.loading-wrap{{text-align:center;padding:60px;color:#8b949e}}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div class="header-title">
      <span style="font-size:1.4rem">🌐</span>
      <h1>Radar · AI 社群地图</h1>
    </div>
    <div class="header-sub">
      更新：{generated_at} &nbsp;·&nbsp;
      <strong>{total_repos:,}</strong> 个来源，共 <strong>{total_items:,}</strong> 个入口
    </div>
    <div class="stat-chips">{stats_html}</div>
  </div>

  <div class="controls">
    <div class="ctrl-row">
      <span class="ctrl-label">🔍 搜索</span>
      <input class="search-input" id="search" type="text"
        placeholder="仓库名 / 标题 / 描述关键词…" oninput="onFilter()">
    </div>
    <div class="ctrl-row">
      <span class="ctrl-label">📡 平台</span>
      <div class="filter-chips" id="plat-chips">
        <button class="chip active" data-plat="" onclick="setPlatform(this)">全部</button>
      </div>
    </div>
  </div>

  <div class="result-bar">
    <div>共 <strong id="result-count">-</strong> 个来源</div>
    <div id="pg-info-top" style="color:#8b949e;font-size:.78rem"></div>
  </div>
  <div id="cards-container">
    <div class="loading-wrap">正在加载…</div>
  </div>
  <div class="pagination">
    <button class="pg-btn" id="pg-prev" onclick="goPage(currentPage-1)">← 上一页</button>
    <span class="pg-info" id="pg-info"></span>
    <button class="pg-btn" id="pg-next" onclick="goPage(currentPage+1)">下一页 →</button>
  </div>
</div>

<script>
const PLATFORM_META = {platform_meta_json};
const PAGE_SIZE = 50;
let REPOS = [], filtered = [], currentPage = 0, activePlat = '';

(async function load() {{
  try {{
    const r = await fetch('{data_url}');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    REPOS = await r.json();
    initPlatChips();
    onFilter();
  }} catch(e) {{
    document.getElementById('cards-container').innerHTML =
      '<div class="empty">❌ 加载失败：' + e.message + '</div>';
  }}
}})();

function initPlatChips() {{
  const plats = {{}};
  REPOS.forEach(r => (r.platforms||[]).forEach(p => plats[p]=(plats[p]||0)+1));
  const c = document.getElementById('plat-chips');
  Object.keys(plats).sort().forEach(p => {{
    const m = PLATFORM_META[p]||{{icon:'🔗',label:p,color:'#888'}};
    const b = document.createElement('button');
    b.className='chip plat-chip'; b.dataset.plat=p;
    b.style.setProperty('--pc',m.color);
    b.innerHTML=m.icon+' '+m.label+' <span style="opacity:.6">('+plats[p]+')</span>';
    b.onclick=()=>setPlatform(b); c.appendChild(b);
  }});
}}

function onFilter() {{
  const q = document.getElementById('search').value.toLowerCase().trim();
  filtered = REPOS.filter(r => {{
    if (activePlat && !(r.platforms||[]).includes(activePlat)) return false;
    if (q && !r.name.toLowerCase().includes(q) && !(r.desc||'').toLowerCase().includes(q)) return false;
    return true;
  }});
  currentPage=0; renderPage();
}}

function setPlatform(btn) {{
  document.querySelectorAll('.plat-chip,[data-plat]').forEach(c=>c.classList.remove('active'));
  btn.classList.add('active'); activePlat=btn.dataset.plat||''; onFilter();
}}

function goPage(p) {{
  const t=Math.ceil(filtered.length/PAGE_SIZE);
  if(p<0||p>=t) return;
  currentPage=p; renderPage(); window.scrollTo({{top:0,behavior:'smooth'}});
}}

function renderPage() {{
  const total=filtered.length, tpg=Math.max(1,Math.ceil(total/PAGE_SIZE));
  const start=currentPage*PAGE_SIZE, sl=filtered.slice(start,start+PAGE_SIZE);
  document.getElementById('result-count').textContent=total.toLocaleString();
  document.getElementById('pg-info').textContent='第'+(currentPage+1)+'/'+tpg+'页';
  document.getElementById('pg-info-top').textContent=total>0?'第'+(start+1)+'-'+Math.min(start+PAGE_SIZE,total)+'条':'';
  document.getElementById('pg-prev').disabled=currentPage===0;
  document.getElementById('pg-next').disabled=currentPage>=tpg-1;
  const c=document.getElementById('cards-container');
  c.innerHTML=total===0?'<div class="empty">😶 无匹配项目</div>':sl.map(renderCard).join('');
}}

function renderCard(r) {{
  const stars=r.stars>=1000?(r.stars/1000).toFixed(1)+'k':String(r.stars);
  const plats=(r.platforms||[]).map(p=>{{
    const m=PLATFORM_META[p]||{{icon:'🔗',label:p,color:'#888'}};
    return '<span class="badge" style="color:'+m.color+'">'+m.icon+' '+m.label+'</span>';
  }}).join('');
  const dispItems=activePlat?(r.items||[]).filter(i=>i.platform===activePlat):(r.items||[]);
  return '<div class="card">' +
    '<div class="card-header">' +
    '<a class="card-name" href="'+esc(r.url)+'" target="_blank" rel="noopener">'+esc(r.name)+'</a>' +
    (r.stars?'<span class="badge">⬆ '+stars+'</span>':'') +
    (r.lang?'<span class="badge">'+esc(r.lang)+'</span>':'') +
    plats + '</div>' +
    (r.desc?'<div class="card-desc">'+esc(r.desc)+'</div>':'') +
    '<div class="items">'+dispItems.map(renderItem).join('')+'</div>' +
    '</div>';
}}

function renderItem(i) {{
  const m=PLATFORM_META[i.platform]||{{icon:'🔗',label:i.platform,color:'#888'}};
  return '<div class="item">' +
    '<div class="item-plat" style="--pc:'+m.color+'">'+m.icon+' '+m.label+'</div>' +
    '<a class="item-link" href="'+esc(i.url)+'" target="_blank" rel="noopener">'+esc(shortUrl(i.url))+'</a>' +
    (i.note?'<div class="item-note">'+esc(i.note)+'</div>':'') +
    '</div>';
}}

function esc(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function shortUrl(u){{
  try{{const x=new URL(u);let s=x.hostname.replace(/^www\./,'')+x.pathname;return s.length>70?s.slice(0,67)+'…':s;}}
  catch{{return(u||'').slice(0,70);}}
}}
</script>
</body>
</html>"""
