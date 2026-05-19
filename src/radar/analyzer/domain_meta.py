"""领域元数据（直接从 agent-radar/score_usecase.py 提取，去掉 SQLite 依赖）

这是静态配置，描述 12 个 AI 领域的市场特征，用于：
1. 项目分类（Tag: namespace=domain）
2. 需求评分 D3/D4 维度（商业化程度 + 市场级别）
3. 报告模板渲染（领域描述文案）
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── 领域元数据 ─────────────────────────────────────────────────────────────
# 来源：openall/agent-radar/src/contexts/scoring/application/score_usecase.py
DOMAIN_META: dict[str, dict] = {
    "coding": {
        "name": "编程开发 Agent", "sub": "AI IDE · 代码补全 · Code Review · DevOps 自动化",
        "commercial": 4, "market_level": 5, "pypi_pkg": "mcp",
        "verdict": "exploding", "verdictLabel": "持续井喷",
        "keywords": ["claude code", "cursor", "copilot", "mcp", "code review", "ide", "devops"],
    },
    "infra": {
        "name": "Agent 基础设施", "sub": "框架 · 协议 · 路由 · 编排 · 评测",
        "commercial": 3, "market_level": 4, "pypi_pkg": "litellm",
        "verdict": "infrawar", "verdictLabel": "基础设施战",
        "keywords": ["litellm", "langchain", "langgraph", "mcp", "agent framework", "orchestration"],
    },
    "browser": {
        "name": "浏览器/GUI Agent", "sub": "网页自动化 · RPA · 爬虫 · 内容采集",
        "commercial": 0, "market_level": 4, "pypi_pkg": "browser-use",
        "big_funding": True,
        "verdict": "gap", "verdictLabel": "需求缺口",
        "keywords": ["browser-use", "playwright", "rpa", "scraping", "web automation", "computer-use"],
    },
    "rag": {
        "name": "RAG / 知识库", "sub": "企业知识库 · 文档问答 · 语义检索 · Wiki",
        "commercial": 3, "market_level": 3, "pypi_pkg": "llama-index-core",
        "verdict": "reshaping", "verdictLabel": "格局重塑",
        "keywords": ["rag", "vector database", "embedding", "knowledge base", "semantic search", "retrieval"],
    },
    "chatbot": {
        "name": "对话机器人 / 客服", "sub": "微信 Bot · 智能客服 · OpenWebUI · 企业助理",
        "commercial": 3, "market_level": 3,
        "verdict": "reshaping", "verdictLabel": "格局重塑",
        "keywords": ["chatbot", "customer service", "wechat bot", "openwebui", "enterprise assistant"],
    },
    "ai4science": {
        "name": "AI × 科研 / 学术", "sub": "论文辅助 · 实验自动化 · 药物发现 · ML 研究",
        "commercial": 2, "market_level": 3,
        "verdict": "gap", "verdictLabel": "低估蓝海",
        "keywords": ["research", "paper", "science", "drug discovery", "bioinformatics", "academic"],
    },
    "personal": {
        "name": "个人 AI 助理", "sub": "日程 · 邮件 · 记忆 · 全能助手 · Second Brain",
        "commercial": 3, "market_level": 4,
        "verdict": "nascent", "verdictLabel": "蓄势待发",
        "keywords": ["personal assistant", "schedule", "email", "memory", "second brain", "productivity"],
    },
    "finance": {
        "name": "金融 / 投资 Agent", "sub": "A 股分析 · 量化策略 · 投资研究 · 财报解读",
        "commercial": 2, "market_level": 4,
        "verdict": "china", "verdictLabel": "中国特供",
        "keywords": ["stock", "finance", "investment", "quant", "trading", "financial analysis"],
    },
    "social": {
        "name": "社媒运营 / 内容 Agent", "sub": "小红书 · 抖音 · 自动发帖 · 账号管理",
        "commercial": 2, "market_level": 4,
        "verdict": "china", "verdictLabel": "中国特供",
        "keywords": ["xiaohongshu", "douyin", "social media", "content generation", "auto post"],
    },
    "creative": {
        "name": "创意 / 生成 Agent", "sub": "AI 绘画 · 视频生成 · 音乐 · ComfyUI 工作流",
        "commercial": 1, "market_level": 2, "pypi_pkg": None,
        "verdict": "zombie", "verdictLabel": "开源失速",
        "keywords": ["stable diffusion", "comfyui", "image generation", "video generation", "music ai"],
    },
    "multimodal": {
        "name": "语音 / 多模态 Agent", "sub": "TTS · 语音助手 · 实时对话 · 多模态理解",
        "commercial": 2, "market_level": 3,
        "verdict": "forming", "verdictLabel": "成形中",
        "keywords": ["tts", "speech", "voice assistant", "multimodal", "realtime", "audio"],
    },
    "hardware": {
        "name": "硬件 / 边缘 Agent", "sub": "ESP32 · IoT · 本地部署 · 嵌入式 AI",
        "commercial": 1, "market_level": 2,
        "verdict": "nascent", "verdictLabel": "早期探索",
        "keywords": ["esp32", "iot", "edge ai", "embedded", "raspberry pi", "local llm"],
    },
}

# 评分基准（来自 score_usecase.py）
_MAX_STARS = 135_653  # obra/superpowers 满分基准


# ── 评分公式 ──────────────────────────────────────────────────────────────


@dataclass
class DomainScore:
    domain_id: str
    score: float       # 0-100 综合需求分
    d3: int            # 商业化程度（0-25）
    d4: int            # 市场级别（0-25）
    supply_level: str  # high / medium / low（基于 github_stars 估算）


def classify_domain(
    title: str,
    content: str,
    topics: list[str],
    language: str = "",
) -> Optional[str]:
    """
    基于关键词匹配，将 Item 分类到最合适的领域。
    返回 domain_id 或 None（无法匹配）。
    """
    text = f"{title} {content} {' '.join(topics)}".lower()
    best_domain: Optional[str] = None
    best_score = 0

    for domain_id, meta in DOMAIN_META.items():
        keywords: list[str] = meta.get("keywords", [])
        match_count = sum(1 for kw in keywords if kw.lower() in text)
        if match_count > best_score:
            best_score = match_count
            best_domain = domain_id

    return best_domain if best_score > 0 else None


def calc_domain_score(domain_id: str, stars: int = 0) -> DomainScore:
    """计算领域评分（D3 + D4 维度）"""
    meta = DOMAIN_META.get(domain_id, {})
    commercial = meta.get("commercial", 0)
    market_level = meta.get("market_level", 1)
    big_funding = meta.get("big_funding", False)

    # D3: 商业化程度（0-25）
    if big_funding:
        d3 = 25
    else:
        d3 = round(min(commercial / 5, 1) * 25)

    # D4: 市场级别（0-25）
    d4 = market_level * 5

    # 供给水平（基于 stars 粗估）
    if stars >= 10000:
        supply_level = "high"
    elif stars >= 1000:
        supply_level = "medium"
    else:
        supply_level = "low"

    # 综合分 = D3 + D4（满分 50，标准化到 0-100）
    score = (d3 + d4) / 50 * 100

    return DomainScore(
        domain_id=domain_id,
        score=round(score, 1),
        d3=d3,
        d4=d4,
        supply_level=supply_level,
    )
