"""E2E 测试：/api/items 已评分条目接口（radar→heyi-eval 发现侧集成面）

验收条件（用户/下游可观察结果）：
  1. 空库时返回空列表，不报错
  2. 已评分 GitHub 条目能被取回，带 stars / QAG 维度 / 领域
  3. min_score 过滤生效；按 QAG 综合分降序
  4. source / domain 过滤生效
  5. scored_only=false 时未评分条目也返回（排在最后）
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _seed(db_url: str) -> None:
    from radar.storage.database import get_session, override_engine
    from radar.storage.models import Item, Score, Tag

    override_engine(db_url)
    async with get_session() as session:
        # 高分 coding 项目
        hi = Item(
            source="github", external_id="o/hi", url="https://github.com/o/hi",
            url_hash="hash-hi", title="hi-agent",
            content="an autonomous coding agent",
            platform_data={"stars": 4200, "language": "Python"},
        )
        session.add(hi)
        await session.flush()
        session.add(Score(
            item_id=hi.id, evaluator="qag", score=0.82,
            dimensions={"pain": 0.9, "market": 0.8, "feasibility": 0.7,
                        "velocity": 0.85, "reason": "强需求"},
            llm_profile="zhipu",
        ))
        session.add(Tag(item_id=hi.id, namespace="domain", value="coding"))

        # 低分 social 项目
        lo = Item(
            source="github", external_id="o/lo", url="https://github.com/o/lo",
            url_hash="hash-lo", title="lo-toy", content="a toy",
            platform_data={"stars": 12},
        )
        session.add(lo)
        await session.flush()
        session.add(Score(
            item_id=lo.id, evaluator="qag", score=0.25,
            dimensions={"pain": 0.2, "market": 0.2, "feasibility": 0.5,
                        "velocity": 0.1, "reason": "小众"},
        ))
        session.add(Tag(item_id=lo.id, namespace="domain", value="social"))

        # 未评分的 reddit 帖
        un = Item(
            source="reddit", external_id="r/x", url="https://reddit.com/x",
            url_hash="hash-un", title="discussion", content="...",
            platform_data={"ups": 30, "subreddit": "LocalLLaMA"},
        )
        session.add(un)


@pytest.mark.asyncio
async def test_items_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/items")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_items_scored_sorted_desc(
    client: AsyncClient, db_url: str, app_with_db,
) -> None:
    await _seed(db_url)
    resp = await client.get("/api/items")
    assert resp.status_code == 200
    data = resp.json()
    # default scored_only=True → only the two scored github items
    assert [d["external_id"] for d in data] == ["o/hi", "o/lo"]
    top = data[0]
    assert top["score"] == 0.82
    assert top["domain"] == "coding"
    assert top["platform_data"]["stars"] == 4200
    assert top["dimensions"]["pain"] == 0.9


@pytest.mark.asyncio
async def test_items_min_score_filter(
    client: AsyncClient, db_url: str, app_with_db,
) -> None:
    await _seed(db_url)
    resp = await client.get("/api/items", params={"min_score": 0.5})
    assert resp.status_code == 200
    data = resp.json()
    assert [d["external_id"] for d in data] == ["o/hi"]


@pytest.mark.asyncio
async def test_items_domain_and_source_filter(
    client: AsyncClient, db_url: str, app_with_db,
) -> None:
    await _seed(db_url)
    resp = await client.get("/api/items", params={"domain": "coding"})
    assert [d["external_id"] for d in resp.json()] == ["o/hi"]

    resp = await client.get("/api/items", params={"source": "reddit"})
    # reddit item is unscored → excluded by default scored_only
    assert resp.json() == []


@pytest.mark.asyncio
async def test_items_include_unscored(
    client: AsyncClient, db_url: str, app_with_db,
) -> None:
    await _seed(db_url)
    resp = await client.get("/api/items", params={"scored_only": "false"})
    data = resp.json()
    ext = [d["external_id"] for d in data]
    # scored first (desc), unscored last
    assert ext[:2] == ["o/hi", "o/lo"]
    assert "r/x" in ext
    unscored = next(d for d in data if d["external_id"] == "r/x")
    assert unscored["score"] is None
