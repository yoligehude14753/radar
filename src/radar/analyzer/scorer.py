"""LLM 评分引擎

功能：
1. 对 Item 进行 QAG 四维度评分（pain / market / feasibility / velocity）
2. 领域分类（domain_id）
3. LLM Profile 切换（heyi / yunwu / ollama）
4. 支持批量重跑（重新评分已有 Item）

遵循 rules: 必须通过 yoli_llm 或 openai 兼容层（不裸调 openai SDK）
暂不依赖 yoli_llm 中台（本项目独立部署），使用 openai 兼容接口。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from radar.config import settings, LLMProfile
from radar.storage.database import get_session
from radar.storage.models import Item, RawBlob, Score, Tag
from radar.analyzer.domain_meta import classify_domain, calc_domain_score, DOMAIN_META

logger = structlog.get_logger(__name__)

# QAG 评分 Prompt（4 维度，输出结构化 JSON）
_SCORE_PROMPT = """你是一个 AI 产品需求分析师。
分析以下 GitHub 项目或 Reddit 帖子，给出四个维度的评分（0.0-1.0）：

1. pain（用户痛点）：解决的问题有多强烈的用户需求
2. market（市场规模）：目标市场的商业潜力（0=个人工具, 1=十亿美元市场）
3. feasibility（技术可行）：当前技术能否实现，竞争壁垒高低
4. velocity（增速信号）：是否处于快速增长期（star 增速/讨论热度）

同时给出最匹配的 AI 领域分类（domain）。

标题：{title}
内容：{content}
Stars：{stars}
Topics：{topics}

请以 JSON 格式返回：
{{
  "pain": 0.8,
  "market": 0.6,
  "feasibility": 0.7,
  "velocity": 0.5,
  "domain": "coding",
  "reason": "简短理由（50字以内）"
}}

domain 必须是以下之一：
coding, infra, browser, rag, chatbot, ai4science, personal, finance, social, creative, multimodal, hardware

只输出 JSON，不要任何其他文字。"""


def _make_llm_client() -> AsyncOpenAI:
    """根据配置的 LLM Profile 创建 OpenAI 兼容客户端"""
    return AsyncOpenAI(
        api_key=settings.llm_api_key or "ollama",
        base_url=settings.llm_base_url,
        timeout=60.0,
    )


async def score_item(item_id: str, force: bool = False) -> Optional[dict]:
    """
    对单个 Item 进行 QAG 评分 + 领域分类。
    force=True 时即使已有评分也重新计算。
    返回评分结果 dict 或 None（失败）。
    """
    async with get_session() as session:
        result = await session.execute(
            select(Item)
            .options(selectinload(Item.raw_blob), selectinload(Item.scores))
            .where(Item.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            logger.warning("Item 不存在", item_id=item_id)
            return None

        # 检查是否已有评分
        if not force and any(s.evaluator == "qag" for s in item.scores):
            logger.debug("Item 已有评分，跳过", item_id=item_id)
            return None

    # 构建 LLM 输入
    platform_data = item.platform_data or {}
    stars = platform_data.get("stars", 0)
    topics = platform_data.get("topics", [])
    content = (item.content or "")[:1000]  # 截断，避免超 token

    prompt = _SCORE_PROMPT.format(
        title=item.title or "",
        content=content,
        stars=stars,
        topics=", ".join(topics[:10]),
    )

    # 调用 LLM
    try:
        client = _make_llm_client()
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("LLM 评分失败", item_id=item_id, error=str(exc))
        return None

    # 解析响应
    try:
        # 提取 JSON（可能有前缀文本）
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"响应中没有 JSON: {raw_text[:200]}")
        score_data = json.loads(raw_text[start:end])
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("LLM 响应解析失败", item_id=item_id, error=str(exc), raw=raw_text[:200])
        return None

    # 验证并归一化
    pain = float(score_data.get("pain", 0))
    market = float(score_data.get("market", 0))
    feasibility = float(score_data.get("feasibility", 0))
    velocity = float(score_data.get("velocity", 0))
    domain_id = score_data.get("domain", "")
    reason = score_data.get("reason", "")

    # 综合分：4 维度加权平均（pain 权重最高）
    composite = (pain * 0.35 + market * 0.30 + feasibility * 0.20 + velocity * 0.15)

    # 写入评分和标签
    async with get_session() as session:
        score = Score(
            item_id=item_id,
            evaluator="qag",
            score=composite,
            dimensions={
                "pain": pain,
                "market": market,
                "feasibility": feasibility,
                "velocity": velocity,
                "reason": reason,
            },
            llm_profile=settings.llm_profile.value,
        )
        session.add(score)

        # 领域标签
        if domain_id and domain_id in DOMAIN_META:
            # 先删旧的 domain tag（重跑时）
            from sqlalchemy import delete
            await session.execute(
                delete(Tag).where(
                    Tag.item_id == item_id,
                    Tag.namespace == "domain",
                )
            )
            session.add(Tag(item_id=item_id, namespace="domain", value=domain_id))

            # 领域评分
            domain_s = calc_domain_score(domain_id, stars=stars)
            session.add(Score(
                item_id=item_id,
                evaluator="domain_classifier",
                score=domain_s.score,
                dimensions={
                    "domain_id": domain_id,
                    "d3": domain_s.d3,
                    "d4": domain_s.d4,
                    "supply_level": domain_s.supply_level,
                },
                llm_profile=settings.llm_profile.value,
            ))
        else:
            # LLM 分类失败，用关键词匹配
            kw_domain = classify_domain(
                title=item.title or "",
                content=item.content or "",
                topics=topics,
            )
            if kw_domain:
                session.add(Tag(item_id=item_id, namespace="domain", value=kw_domain))

    logger.info(
        "Item 评分完成",
        item_id=item_id[:8],
        score=round(composite, 3),
        domain=domain_id,
    )
    return {
        "item_id": item_id,
        "score": composite,
        "pain": pain,
        "market": market,
        "feasibility": feasibility,
        "velocity": velocity,
        "domain": domain_id,
        "reason": reason,
    }


async def score_unscored_items(
    source: Optional[str] = None,
    limit: int = 100,
    force: bool = False,
) -> dict:
    """
    批量评分：从数据库中取未评分的 Item，逐个评分。
    source=None 时处理所有源。
    """
    import asyncio

    # 查询未评分的 Item
    async with get_session() as session:
        # 子查询：已有 qag 评分的 item_id
        scored_subq = select(Score.item_id).where(Score.evaluator == "qag")

        q = select(Item.id).order_by(Item.fetched_at.desc()).limit(limit)
        if source:
            q = q.where(Item.source == source)
        if not force:
            q = q.where(Item.id.not_in(scored_subq))

        result = await session.execute(q)
        item_ids = [row.id for row in result]

    if not item_ids:
        logger.info("没有需要评分的 Item", source=source)
        return {"status": "ok", "scored": 0, "failed": 0}

    logger.info("开始批量评分", count=len(item_ids), source=source)
    scored = 0
    failed = 0

    for item_id in item_ids:
        result = await score_item(item_id, force=force)
        if result:
            scored += 1
        else:
            failed += 1
        # 限速：避免 LLM API 过载
        await asyncio.sleep(0.5)

    logger.info("批量评分完成", scored=scored, failed=failed)
    return {"status": "ok", "scored": scored, "failed": failed}
