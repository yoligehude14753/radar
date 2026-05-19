"""Reddit OAuth 凭证采集向导"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt

console = Console()


class RedditOAuthWizard:
    """
    交互式引导用户创建 Reddit OAuth App 并获取 client_id/secret。
    Reddit 公开 API 无需任何配置即可使用，OAuth 仅为提升速率限制。
    """

    STEPS = [
        "打开 [link]https://www.reddit.com/prefs/apps[/link]",
        "点击「are you a developer? create an app」",
        "name 填：Radar AI Tracker",
        "选择「script」类型",
        "description：AI 需求趋势追踪工具",
        "about url / redirect uri 填：http://localhost",
        "点击「create app」",
        "复制「client id」（app 名下方的短字符串）和「secret」",
    ]

    async def harvest(self, timeout_s: float = 300) -> Optional[dict]:
        """
        引导用户完成 OAuth App 创建，返回 {"client_id": ..., "client_secret": ...} 或 None。
        注意：Reddit 公开 API 无需 OAuth，可以直接跳过。
        """
        console.print("\n[bold cyan]━━━ Reddit OAuth 配置向导 ━━━[/]\n")
        console.print(
            "[yellow]💡 提示：Reddit 公开 API 无需配置即可使用[/]\n"
            "   配置 OAuth 后速率限制从 30 req/10min 提升至 60 req/min\n"
        )

        skip = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: Prompt.ask(
                "是否跳过（直接使用公开 API）？",
                choices=["y", "n"],
                default="y",
            ),
        )

        if skip.lower() == "y":
            console.print("[green]✓[/] 使用公开 API 模式，无需配置")
            return None

        console.print("\n[bold]创建步骤：[/]")
        for i, step in enumerate(self.STEPS, 1):
            console.print(f"  [cyan]{i}.[/] {step}")
        console.print()

        loop = asyncio.get_event_loop()
        client_id = await loop.run_in_executor(
            None,
            lambda: Prompt.ask("[bold yellow]请粘贴 client id[/]"),
        )
        client_secret = await loop.run_in_executor(
            None,
            lambda: Prompt.ask("[bold yellow]请粘贴 secret[/]"),
        )

        client_id = client_id.strip()
        client_secret = client_secret.strip()

        if not client_id or not client_secret:
            console.print("[red]✗ client_id 或 secret 不能为空[/]")
            return None

        # 验证凭证
        is_valid = await self._verify(client_id, client_secret)
        if not is_valid:
            console.print("[red]✗ OAuth 凭证验证失败[/]")
            return None

        console.print("[green]✓ Reddit OAuth 凭证验证成功！[/]")
        return {"client_id": client_id, "client_secret": client_secret}

    async def _verify(self, client_id: str, client_secret: str) -> bool:
        from radar.sources.reddit.client import RedditClient
        try:
            async with RedditClient(client_id=client_id, client_secret=client_secret) as client:
                return await client.health_check()
        except Exception:
            return False
