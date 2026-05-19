"""数据库模型 - 6张主表 + Incident/IncidentAction"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# 兼容 PG 和 SQLite 的 JSON 类型
def _json_col():
    """根据数据库类型返回合适的 JSON 列类型"""
    try:
        return JSONB
    except Exception:
        return JSON


class Base(DeclarativeBase):
    pass


# ── L1 输出 / L2 存储 ─────────────────────────────────────────────────────


class SourceRun(Base):
    """每次抓取任务的运行记录（含增量 cursor）"""
    __tablename__ = "source_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cursor: Mapped[Optional[str]] = mapped_column(Text)          # 增量游标（时间戳/ID）
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending / running / done / failed
    items_in: Mapped[int] = mapped_column(Integer, default=0)    # 本次抓到的原始条目
    items_new: Mapped[int] = mapped_column(Integer, default=0)   # 去重后新增条目
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    items: Mapped[list["Item"]] = relationship("Item", back_populates="source_run")

    __table_args__ = (
        Index("ix_source_runs_source_created", "source", "created_at"),
    )


class Item(Base):
    """统一的内容条目（跨 GitHub / Reddit 等所有源）"""
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(Text)
    content: Mapped[Optional[str]] = mapped_column(Text)
    # 平台专属字段（GitHub: stars/issues/commits; Reddit: ups/comments/subreddit）
    platform_data: Mapped[Optional[dict]] = mapped_column(JSON)
    source_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("source_runs.id", ondelete="SET NULL"), index=True
    )
    item_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # 内容发布时间
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    source_run: Mapped[Optional["SourceRun"]] = relationship("SourceRun", back_populates="items")
    scores: Mapped[list["Score"]] = relationship("Score", back_populates="item", cascade="all, delete-orphan")
    tags: Mapped[list["Tag"]] = relationship("Tag", back_populates="item", cascade="all, delete-orphan")
    raw_blob: Mapped[Optional["RawBlob"]] = relationship("RawBlob", back_populates="item", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_item_source_external"),
        Index("ix_items_source_fetched", "source", "fetched_at"),
        Index("ix_items_item_at", "item_at"),
    )


class RawBlob(Base):
    """原始 payload 全量留档（重跑评分时无需重抓）"""
    __tablename__ = "raw_blobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), unique=True, index=True
    )
    payload: Mapped[Optional[str]] = mapped_column(Text)         # JSON 序列化的原始响应
    content_type: Mapped[str] = mapped_column(String(64), default="application/json")
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    item: Mapped["Item"] = relationship("Item", back_populates="raw_blob")


# ── L3 分析 ────────────────────────────────────────────────────────────────


class Score(Base):
    """评分记录（支持同一 Item 多次评分，历史可追溯）"""
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluator: Mapped[str] = mapped_column(String(64), nullable=False)  # "qag" / "domain_classifier"
    score: Mapped[Optional[float]] = mapped_column(Float)
    # 评分细节：QAG维度 / LLM analysis_verdict/progress/pain/focus / domain分类
    dimensions: Mapped[Optional[dict]] = mapped_column(JSON)
    llm_profile: Mapped[Optional[str]] = mapped_column(String(32))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    item: Mapped["Item"] = relationship("Item", back_populates="scores")

    __table_args__ = (
        Index("ix_scores_item_evaluator", "item_id", "evaluator"),
        Index("ix_scores_scored_at", "scored_at"),
    )


class Tag(Base):
    """标签（命名空间化，如 domain/category/keyword）"""
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)  # "domain" / "category" / "keyword"
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    item: Mapped["Item"] = relationship("Item", back_populates="tags")

    __table_args__ = (
        UniqueConstraint("item_id", "namespace", "value", name="uq_tag_item_ns_value"),
        Index("ix_tags_namespace_value", "namespace", "value"),
    )


# ── L4 输出 ────────────────────────────────────────────────────────────────


class Report(Base):
    """后台 cron 每次自动渲染的产物记录"""
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # "projects" / "communities"
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)   # "2026-05-19"
    params: Mapped[Optional[dict]] = mapped_column(JSON)                  # 渲染参数快照
    file_path: Mapped[Optional[str]] = mapped_column(Text)                # 磁盘路径
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")    # pending / ok / failed
    error: Mapped[Optional[str]] = mapped_column(Text)
    llm_profile: Mapped[Optional[str]] = mapped_column(String(32))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("template", "period_key", name="uq_report_template_period"),
        Index("ix_reports_template_generated", "template", "generated_at"),
    )


# ── 监控 / Incident ─────────────────────────────────────────────────────────


class Incident(Base):
    """监控引擎发现的停滞事件"""
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    signal_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # source_failing / token_expiring / data_stale 等 12 类
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="warning"
    )  # info / warning / critical
    affected_resource: Mapped[Optional[str]] = mapped_column(String(256))  # "github" / "reddit" / "token:github"
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    context_data: Mapped[Optional[dict]] = mapped_column(JSON)   # 发现时的现场数据
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", index=True
    )  # open / resolving / resolved / dismissed
    resolution: Mapped[Optional[str]] = mapped_column(String(128))  # 用了哪个 action_key 解决
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    actions: Mapped[list["IncidentAction"]] = relationship(
        "IncidentAction", back_populates="incident", cascade="all, delete-orphan",
        order_by="IncidentAction.order"
    )

    __table_args__ = (
        # 同类同源 24h 内去重靠应用层逻辑，这里加索引加速查询
        Index("ix_incidents_signal_resource_status", "signal_type", "affected_resource", "status"),
        Index("ix_incidents_detected_at", "detected_at"),
    )


class IncidentAction(Base):
    """每个 Incident 可以执行的修复动作"""
    __tablename__ = "incident_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_key: Mapped[str] = mapped_column(String(64), nullable=False)   # "retry_source" / "refresh_token" 等
    label: Mapped[str] = mapped_column(String(128), nullable=False)       # 展示给用户的文案
    endpoint: Mapped[Optional[str]] = mapped_column(String(256))          # API 端点（Web UI 用）
    order: Mapped[int] = mapped_column(Integer, default=0)                # 展示顺序（0=主推）
    last_error: Mapped[Optional[str]] = mapped_column(Text)               # 执行失败时记录
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="actions")
