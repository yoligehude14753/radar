"""异步 GitHub REST API 客户端（整合自 agent-radar/github_client.py）

升级：
- requests → httpx async（与 FastAPI 事件循环兼容）
- 支持 GitHub PAT 认证（速率限制 5000 req/h vs 未认证 60 req/h）
- 自动处理速率限制（429/403 + Retry-After）
- 增量游标（since_date）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"


class GitHubClient:
    def __init__(self, token: str = "") -> None:
        headers = {
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=_BASE,
            headers=headers,
            timeout=20.0,
            follow_redirects=True,
        )
        self._token = token

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self._client.aclose()

    async def close(self) -> None:
        await self._client.aclose()

    # ── 限速处理 ──────────────────────────────────────────────────────────

    async def _get(self, path: str, params: Optional[dict] = None) -> dict | list:
        for attempt in range(4):
            try:
                resp = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                logger.warning("GitHub HTTP 错误: %s (attempt %d)", exc, attempt + 1)
                if attempt == 3:
                    raise
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (403, 429):
                retry_after = int(resp.headers.get("Retry-After", "60"))
                reset_at = resp.headers.get("X-RateLimit-Reset")
                if reset_at:
                    wait = max(0, int(reset_at) - int(datetime.now(timezone.utc).timestamp())) + 5
                else:
                    wait = retry_after
                logger.warning("GitHub 速率限制，等待 %ds...", wait)
                await asyncio.sleep(min(wait, 300))  # 最多等 5 分钟
                continue

            if resp.status_code == 401:
                raise ValueError(f"GitHub Token 无效或已过期（401）: {path}")

            if resp.status_code == 404:
                return {}

            logger.warning("GitHub 返回 %d: %s", resp.status_code, path)
            return {}

        return {}

    # ── 速率限制查询 ──────────────────────────────────────────────────────

    async def get_rate_limit(self) -> dict:
        """返回当前速率限制状态"""
        result = await self._get("/rate_limit")
        return result.get("resources", {}).get("core", {}) if result else {}

    # ── 仓库信息 ──────────────────────────────────────────────────────────

    async def get_repo(self, full_name: str) -> dict:
        """获取单个仓库详情"""
        return await self._get(f"/repos/{full_name}")  # type: ignore

    async def get_repo_stars(self, full_name: str) -> Optional[int]:
        """获取 star 数，失败返回 None"""
        data = await self.get_repo(full_name)
        return data.get("stargazers_count") if data else None

    # ── 搜索（整合自 agent-radar/github_client.py）────────────────────────

    async def search_repos(
        self,
        keywords: list[str],
        since_date: str,
        max_results: int = 50,
        sort: str = "stars",
    ) -> list[dict]:
        """
        搜索关键词相关仓库（增量游标：since_date='2026-05-01'）。
        返回标准化字段列表，兼容 agent-radar 的格式。
        """
        # 最多 3 个关键词避免查询过宽（Search API 限制）
        q = " OR ".join(f'"{kw}"' for kw in keywords[:3])
        q += f" created:>{since_date}"
        params = {
            "q": q,
            "sort": sort,
            "order": "desc",
            "per_page": min(max_results, 100),
        }
        data = await self._get("/search/repositories", params=params)
        items = data.get("items", []) if isinstance(data, dict) else []

        return [self._normalize_repo(it) for it in items]

    async def search_repos_by_query(
        self,
        query: str,
        max_results: int = 50,
        sort: str = "updated",
    ) -> list[dict]:
        """用完整的 GitHub 搜索 query 搜索"""
        params = {
            "q": query,
            "sort": sort,
            "order": "desc",
            "per_page": min(max_results, 100),
        }
        data = await self._get("/search/repositories", params=params)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [self._normalize_repo(it) for it in items]

    async def get_trending_repos(self, since_date: str, max_results: int = 50) -> list[dict]:
        """获取 AI 相关热门仓库（按 star 排序）"""
        # 使用 agent-radar 经过验证的关键词集合
        ai_keywords = ["llm", "agent", "mcp", "openai", "claude", "gemini", "rag", "embedding"]
        results: list[dict] = []
        seen: set[str] = set()

        # 分批搜索避免单次过多，每批 3 个关键词
        for i in range(0, len(ai_keywords), 3):
            batch = ai_keywords[i:i+3]
            batch_results = await self.search_repos(
                keywords=batch,
                since_date=since_date,
                max_results=min(max_results, 30),
                sort="stars",
            )
            for r in batch_results:
                if r["full_name"] not in seen:
                    seen.add(r["full_name"])
                    results.append(r)
            # 批次间限速（Search API: 10 req/min 未认证, 30 req/min 认证）
            await asyncio.sleep(2 if self._token else 6)

        # 按 star 数倒序，取 top N
        results.sort(key=lambda x: x.get("stars", 0), reverse=True)
        return results[:max_results]

    # ── 格式标准化 ────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_repo(raw: dict) -> dict:
        """标准化 GitHub API 返回格式"""
        return {
            "full_name": raw.get("full_name", ""),
            "html_url": raw.get("html_url", ""),
            "description": raw.get("description") or "",
            "stars": raw.get("stargazers_count", 0),
            "forks": raw.get("forks_count", 0),
            "open_issues": raw.get("open_issues_count", 0),
            "language": raw.get("language") or "",
            "topics": raw.get("topics", []),
            "license": (raw.get("license") or {}).get("spdx_id", ""),
            "created_at": raw.get("created_at", ""),
            "updated_at": raw.get("updated_at", ""),
            "pushed_at": raw.get("pushed_at", ""),
            "owner_login": (raw.get("owner") or {}).get("login", ""),
            "owner_type": (raw.get("owner") or {}).get("type", ""),
            "is_fork": raw.get("fork", False),
            "is_archived": raw.get("archived", False),
            "watchers": raw.get("watchers_count", 0),
        }
