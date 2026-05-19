"""
E2E 测试：LLM 评分全链路

验收条件（用户可观察结果）：
  1. 抓取 Item 后，评分任务能写入 Score 记录
  2. 评分包含 4 个维度（pain/market/feasibility/velocity）
  3. 领域分类正确写入 Tag（namespace=domain）
  4. LLM 返回格式错误时能优雅降级（不崩溃，不写脏数据）
  5. 重跑（force=True）能覆盖旧评分
  6. 未评分 Item 计数正确
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_LLM_RESPONSE = json.dumps({
    "pain": 0.85,
    "market": 0.70,
    "feasibility": 0.75,
    "velocity": 0.60,
    "domain": "coding",
    "reason": "MCP 工具生态，开发者痛点强",
})

MOCK_LLM_INVALID = "这是一段没有 JSON 的文本，模型没按格式输出"


async def _seed_item(session, source: str = "github", title: str = "test/mcp-tool") -> str:
    """创建一个测试 Item，返回 item_id"""
    from radar.storage.models import Item
    url = f"https://github.com/{title}"
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    item = Item(
        source=source,
        external_id=title,
        url=url,
        url_hash=url_hash,
        title=title,
        content="A MCP server tool for AI coding assistants. Supports Claude Code and Cursor.",
        platform_data={"stars": 1500, "topics": ["mcp", "ai", "claude"], "language": "Python"},
        item_at=datetime.now(timezone.utc),
    )
    session.add(item)
    await session.flush()
    return item.id


def _mock_llm_response(content: str):
    """构造 mock 的 OpenAI API 返回"""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_score_item_writes_score_and_tag(db_url: str) -> None:
    """
    核心 E2E：LLM 评分 → Score 记录写入 → domain Tag 写入
    验收：Score 存在，domain Tag 为 coding
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Score, Tag
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        item_id = await _seed_item(session)

    with patch("radar.analyzer.scorer.AsyncOpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(MOCK_LLM_RESPONSE)
        )
        MockOpenAI.return_value = mock_client

        from radar.analyzer.scorer import score_item
        result = await score_item(item_id)

    assert result is not None
    assert result["domain"] == "coding"
    assert 0 < result["score"] <= 1.0
    assert result["pain"] == 0.85

    async with get_session() as session:
        scores = (await session.execute(
            select(Score).where(Score.item_id == item_id)
        )).scalars().all()
        assert len(scores) >= 1

        qag_score = next((s for s in scores if s.evaluator == "qag"), None)
        assert qag_score is not None
        assert qag_score.dimensions["pain"] == 0.85
        assert qag_score.dimensions["market"] == 0.70

        tags = (await session.execute(
            select(Tag).where(Tag.item_id == item_id, Tag.namespace == "domain")
        )).scalars().all()
        assert len(tags) == 1
        assert tags[0].value == "coding"


@pytest.mark.asyncio
async def test_score_item_llm_invalid_response_no_crash(db_url: str) -> None:
    """
    LLM 返回格式错误时：不写入脏数据，不崩溃，返回 None
    验收：DB 中没有 Score 记录
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Score
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        item_id = await _seed_item(session, title="test/bad-llm-item")

    with patch("radar.analyzer.scorer.AsyncOpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(MOCK_LLM_INVALID)
        )
        MockOpenAI.return_value = mock_client

        from radar.analyzer.scorer import score_item
        result = await score_item(item_id)

    assert result is None, "LLM 响应非法时应返回 None"

    async with get_session() as session:
        count = len((await session.execute(
            select(Score).where(Score.item_id == item_id)
        )).scalars().all())
        assert count == 0, "不应写入任何评分"


@pytest.mark.asyncio
async def test_score_skip_already_scored(db_url: str) -> None:
    """已有评分的 Item 默认不重新评分（force=False）"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Score
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        item_id = await _seed_item(session, title="test/already-scored")

    with patch("radar.analyzer.scorer.AsyncOpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(MOCK_LLM_RESPONSE)
        )
        MockOpenAI.return_value = mock_client

        from radar.analyzer.scorer import score_item

        # 第一次评分
        r1 = await score_item(item_id)
        assert r1 is not None

        # 第二次（不强制）应跳过
        r2 = await score_item(item_id, force=False)
        assert r2 is None

        # LLM 只被调用一次
        assert mock_client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_score_force_reruns(db_url: str) -> None:
    """force=True 时重新评分"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Score
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        item_id = await _seed_item(session, title="test/force-rescore")

    with patch("radar.analyzer.scorer.AsyncOpenAI") as MockOpenAI, \
         patch("radar.analyzer.scorer.asyncio.sleep", new_callable=AsyncMock):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(MOCK_LLM_RESPONSE)
        )
        MockOpenAI.return_value = mock_client

        from radar.analyzer.scorer import score_item

        await score_item(item_id)
        r2 = await score_item(item_id, force=True)

    assert r2 is not None
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_batch_scoring_unscored_items(db_url: str) -> None:
    """
    批量评分：3 个 Item，全部未评分，应全部完成
    验收：scored=3，failed=0
    """
    from radar.storage.database import override_engine, init_db, get_session

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        for i in range(3):
            await _seed_item(session, title=f"test/batch-item-{i}")

    with patch("radar.analyzer.scorer.AsyncOpenAI") as MockOpenAI, \
         patch("radar.analyzer.scorer.asyncio.sleep", new_callable=AsyncMock):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(MOCK_LLM_RESPONSE)
        )
        MockOpenAI.return_value = mock_client

        from radar.analyzer.scorer import score_unscored_items
        result = await score_unscored_items(limit=10)

    assert result["scored"] == 3
    assert result["failed"] == 0
