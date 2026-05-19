"""GitHub Token 采集策略（交互式引导）

参考 aha/projects/aha/src/auth/strategies/api_key.py 的 ApiKeyStrategy 模式，
适配 radar 的简化版本（不依赖 aha 的 StoredCredential 体系）。
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt

console = Console()

# PAT 格式：ghp_xxx (classic) 或 github_pat_xxx (fine-grained)
_TOKEN_RE = re.compile(r"^(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})$")


class GitHubTokenWizard:
    """
    交互式引导用户生成 GitHub Personal Access Token。
    输出：有效的 token 字符串，或 None（用户跳过）。
    """

    REQUIRED_SCOPES = ["public_repo", "read:org"]
    STEPS = [
        "打开 [link]https://github.com/settings/tokens/new[/link]",
        "Note（备注）填：Radar AI 趋势抓取",
        "Expiration（有效期）选：90 days",
        f"Scopes 勾选：[bold]{', '.join(REQUIRED_SCOPES)}[/bold]",
        "点击「Generate token」并复制 token 值",
    ]

    async def harvest(self, timeout_s: float = 300) -> Optional[str]:
        """引导用户完成 Token 生成，返回有效 token 或 None"""
        console.print("\n[bold cyan]━━━ GitHub Token 配置向导 ━━━[/]\n")
        console.print(
            "Radar 需要 GitHub PAT 来突破 API 速率限制\n"
            "（未认证：60 次/小时 → 认证后：5000 次/小时）\n"
        )
        console.print("[bold]操作步骤：[/]")
        for i, step in enumerate(self.STEPS, 1):
            console.print(f"  [cyan]{i}.[/] {step}")

        console.print()
        token = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: Prompt.ask(
                "[bold yellow]请粘贴你的 GitHub Token[/]（输入 s 跳过，使用匿名模式）",
                default="s",
            ),
        )

        if token.strip().lower() == "s":
            console.print("[yellow]⚠ 跳过 Token 配置，使用匿名模式（速率限制 60 次/小时）[/]")
            return None

        token = token.strip()
        if not self._validate(token):
            console.print(
                "[red]✗ Token 格式不正确[/]（应以 ghp_ 或 github_pat_ 开头）\n"
                "请重新运行 [cyan]radar token github --action wizard[/] 配置"
            )
            return None

        # 验证 token 有效性
        is_valid = await self._verify_token(token)
        if not is_valid:
            console.print("[red]✗ Token 验证失败[/]（可能已过期或权限不足）")
            return None

        console.print("[green]✓ GitHub Token 验证成功！[/]")
        return token

    def _validate(self, token: str) -> bool:
        """格式校验"""
        return bool(_TOKEN_RE.match(token))

    async def _verify_token(self, token: str) -> bool:
        """实际调用 API 验证 token 有效性"""
        from radar.sources.github.client import GitHubClient
        try:
            async with GitHubClient(token=token) as client:
                rate = await client.get_rate_limit()
                return rate.get("limit", 0) > 60  # 认证后应该 > 60
        except Exception:
            return False
