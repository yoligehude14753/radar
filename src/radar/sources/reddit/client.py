"""异步 Reddit 客户端（迁移自 aha/adapters/reddit.py）

两级访问：
- 公开 JSON API（零配置，~30 req/10min）
- OAuth client_credentials（配置 REDDIT_CLIENT_ID/SECRET，60 QPM）
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PUBLIC_HEADERS = {
    "User-Agent": "radar-ai-trend-tracker/0.1.0 (opensource)",
    "Accept": "application/json",
}

# radar 关注的 AI 相关 subreddit（专注 AI/技术需求）
AI_SUBREDDITS = [
    "artificial",
    "MachineLearning",
    "LocalLLaMA",
    "ChatGPT",
    "ClaudeAI",
    "singularity",
    "learnmachinelearning",
    "programming",
    "SideProject",
    "SaaS",
    "indiehackers",
    "OpenAI",
    "LangChain",
]


def _jitter(lo: float = 1.0, hi: float = 3.0) -> float:
    return random.uniform(lo, hi)


class RedditClient:
    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "radar-ai-trend-tracker/0.1.0",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._client: Optional[httpx.AsyncClient] = None

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={**_PUBLIC_HEADERS, "User-Agent": self._user_agent},
            follow_redirects=True,
            timeout=20.0,
        )

    async def __aenter__(self) -> "RedditClient":
        self._client = self._make_client()
        if self._client_id:
            await self._refresh_token()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    # ── OAuth ─────────────────────────────────────────────────────────────

    async def _refresh_token(self) -> None:
        if not (self._client_id and self._client_secret):
            return
        try:
            r = await self._client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                self._token = data.get("access_token")
                self._token_expires = time.time() + data.get("expires_in", 3600) - 60
                logger.info("Reddit OAuth token 刷新成功")
        except Exception as exc:
            logger.warning("Reddit OAuth token 获取失败: %s", exc)
            self._token = None

    async def _ensure_token(self) -> None:
        if self._client_id and (not self._token or time.time() > self._token_expires):
            await self._refresh_token()

    def _base_url(self) -> str:
        return "https://oauth.reddit.com" if self._token else "https://www.reddit.com"

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    # ── API 调用 ──────────────────────────────────────────────────────────

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        await self._ensure_token()
        url = f"{self._base_url()}{path}"
        for attempt in range(3):
            try:
                r = await self._client.get(url, params=params, headers=self._auth_headers())
            except httpx.HTTPError as exc:
                logger.warning("Reddit HTTP 错误: %s (attempt %d)", exc, attempt + 1)
                await asyncio.sleep(2 ** attempt)
                continue

            if r.status_code == 200:
                return r.json()

            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", "60"))
                logger.warning("Reddit 速率限制，等待 %ds", retry_after)
                await asyncio.sleep(min(retry_after, 120))
                continue

            if r.status_code == 401:
                if self._client_id and attempt == 0:
                    await self._refresh_token()
                    continue
                raise PermissionError(f"Reddit 认证失败 401: {path}（token 已失效）")

            if r.status_code == 403:
                # Reddit 公开 API 已要求 OAuth，无 token 时全部 403
                msg = (
                    f"Reddit 返回 403: {path}。"
                    "Reddit 已禁止匿名访问，请配置 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET。"
                    "引导：radar token reddit"
                )
                raise PermissionError(msg)

            logger.warning("Reddit 返回 %d: %s", r.status_code, path)
            return {}

        return {}

    # ── 搜索 API ──────────────────────────────────────────────────────────

    async def search_subreddit(
        self,
        subreddit: str,
        query: str,
        sort: str = "relevance",
        time_filter: str = "week",
        limit: int = 25,
    ) -> list[dict]:
        """在指定 subreddit 中搜索帖子"""
        data = await self._get(
            f"/r/{subreddit}/search.json",
            params={
                "q": query,
                "sort": sort,
                "t": time_filter,
                "limit": min(limit, 100),
                "restrict_sr": "true",
                "type": "link",
            },
        )
        posts = data.get("data", {}).get("children", [])
        return [self._normalize_post(p["data"]) for p in posts if p.get("kind") == "t3"]

    async def get_subreddit_new(
        self,
        subreddit: str,
        limit: int = 25,
        after: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str]]:
        """
        获取 subreddit 最新帖子，返回 (posts, next_after_cursor)
        """
        params: dict = {"limit": min(limit, 100), "raw_json": "1"}
        if after:
            params["after"] = after

        data = await self._get(f"/r/{subreddit}/new.json", params=params)
        listing = data.get("data", {})
        posts = listing.get("children", [])
        next_after = listing.get("after")

        return (
            [self._normalize_post(p["data"]) for p in posts if p.get("kind") == "t3"],
            next_after,
        )

    async def get_subreddit_hot(self, subreddit: str, limit: int = 25) -> list[dict]:
        """获取 subreddit 热门帖子"""
        data = await self._get(f"/r/{subreddit}/hot.json", params={"limit": min(limit, 100)})
        posts = data.get("data", {}).get("children", [])
        return [self._normalize_post(p["data"]) for p in posts if p.get("kind") == "t3"]

    # ── 健康检查 ──────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """检查 Reddit API 是否可达"""
        data = await self._get("/r/artificial/hot.json", params={"limit": 1})
        return bool(data)

    # ── 格式标准化（与 aha/reddit.py 兼容）───────────────────────────────

    @staticmethod
    def _normalize_post(raw: dict) -> dict:
        created_utc = raw.get("created_utc", 0)
        created_at = ""
        if created_utc:
            from datetime import datetime, timezone
            created_at = datetime.fromtimestamp(created_utc, timezone.utc).isoformat()

        return {
            "post_id": raw.get("id", ""),
            "full_name": raw.get("name", ""),  # t3_xxx
            "subreddit": raw.get("subreddit", ""),
            "title": raw.get("title", ""),
            "selftext": (raw.get("selftext") or "")[:2000],  # 截断超长正文
            "url": f"https://reddit.com{raw.get('permalink', '')}",
            "author": raw.get("author", ""),
            "ups": raw.get("ups", 0),
            "upvote_ratio": raw.get("upvote_ratio", 0.0),
            "num_comments": raw.get("num_comments", 0),
            "score": raw.get("score", 0),
            "total_awards": raw.get("total_awards_received", 0),
            "is_self": raw.get("is_self", True),
            "link_flair_text": raw.get("link_flair_text") or "",
            "created_at": created_at,
            "domain": raw.get("domain", ""),
        }
