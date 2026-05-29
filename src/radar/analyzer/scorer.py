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
import re
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
_SCORE_PROMPT = """你是一个 AI 产品需求分析师。请独立分析以下项目，给出真实评分，不要使用固定值。

项目信息：
标题：{title}
内容：{content}
Stars：{stars}
Topics：{topics}

评分维度（每项独立判断，范围 0.0-1.0，必须体现差异）：
- pain：用户痛点强度（0=无明显痛点，1=极强烈需求，如生产力瓶颈/安全漏洞）
- market：市场规模潜力（0=极小众个人工具，1=数十亿规模平台级市场）
- feasibility：技术可行性（0=核心技术尚未突破，1=成熟技术栈易实现）
- velocity：增速信号（0=停滞/下降，1=病毒式传播/星数周翻番）

判断标准：
- Stars>{stars_threshold}：velocity 应 >= 0.6
- 纯个人工具/hobby project：market 应 <= 0.3
- 与 OpenAI/Claude 强竞争：feasibility 应 <= 0.4

领域（从以下选一个最匹配）：
coding（编程工具）, infra（基础设施）, browser（浏览器/UI）, rag（检索增强）,
chatbot（对话机器人）, ai4science（科学AI）, personal（个人助理）, finance（金融）,
social（社交/内容）, creative（创意生成）, multimodal（多模态）, hardware（硬件/端侧）

仅输出 JSON，格式如下（所有数值必须真实计算，禁止照抄示例）：
{{"pain": <float>, "market": <float>, "feasibility": <float>, "velocity": <float>, "domain": "<id>", "reason": "<30字内理由>"}}"""


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

    stars_threshold = 500 if stars > 500 else (100 if stars > 100 else 10)
    prompt = _SCORE_PROMPT.format(
        title=item.title or "",
        content=content,
        stars=stars,
        topics=", ".join(topics[:10]) or "无",
        stars_threshold=stars_threshold,
    )

    # 调用 LLM
    try:
        client = _make_llm_client()
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            # Thinking models (e.g. MiniMax-M2.7) emit a long <think> block
            # before the JSON; 300 tokens was all spent thinking so the JSON
            # never appeared. Give ample room — the JSON itself is tiny.
            max_tokens=4096,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("LLM 评分失败", item_id=item_id, error=str(exc))
        return None

    # 解析响应。Thinking 模型会输出 <think>…</think> 推理块（甚至带
    # markdown），需先剥离再提取 JSON（取最外层 {…}）。
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    try:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"响应中没有 JSON: {raw_text[:200]}")
        score_data = json.loads(cleaned[start:end])
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

    # 写入评分和标签（先删旧记录，避免重复）
    async with get_session() as session:
        from sqlalchemy import delete
        await session.execute(
            delete(Score).where(Score.item_id == item_id, Score.evaluator == "qag")
        )
        await session.execute(
            delete(Score).where(Score.item_id == item_id, Score.evaluator == "domain_classifier")
        )
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
