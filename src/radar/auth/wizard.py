"""Token 管理向导入口"""
from __future__ import annotations

from rich.console import Console

console = Console()


async def run_wizard(source: str, action: str = "status") -> None:
    """根据 source 分发到对应向导"""
    if source == "github":
        await _github_wizard(action)
    elif source == "reddit":
        await _reddit_wizard(action)
    else:
        console.print(f"[red]未知数据源: {source}[/]（支持：github / reddit）")


async def _github_wizard(action: str) -> None:
    if action == "wizard":
        from radar.auth.strategies.github import GitHubTokenWizard
        wizard = GitHubTokenWizard()
        token = await wizard.harvest()
        if token:
            console.print(
                "\n[bold green]下一步：[/] 将 Token 写入 .env 文件：\n"
                f"  [cyan]GITHUB_TOKEN={token}[/]\n"
                "然后重启 radar 服务即可生效。"
            )
    elif action == "status":
        from radar.config import settings
        if settings.github_token:
            from radar.sources.github.client import GitHubClient
            try:
                async with GitHubClient(token=settings.github_token) as client:
                    rate = await client.get_rate_limit()
                remaining = rate.get("remaining", "?")
                limit = rate.get("limit", "?")
                reset_ts = rate.get("reset", 0)
                from datetime import datetime, timezone
                reset_str = datetime.fromtimestamp(reset_ts, timezone.utc).strftime("%H:%M:%S") if reset_ts else "?"
                console.print(f"[green]✓[/] GitHub Token 有效 | 剩余请求: {remaining}/{limit} | 重置时间: {reset_str}")
            except Exception as exc:
                console.print(f"[red]✗[/] GitHub Token 验证失败: {exc}")
        else:
            console.print(
                "[yellow]⚠[/] GitHub Token 未配置（匿名模式：60 次/小时）\n"
                "运行 [cyan]radar token github --action wizard[/] 配置 Token"
            )
    elif action == "refresh":
        console.print("GitHub PAT 不支持自动刷新，请重新运行 wizard 生成新 Token：")
        await _github_wizard("wizard")
    else:
        console.print(f"[red]未知 action: {action}[/]（支持：status / wizard / refresh）")


async def _reddit_wizard(action: str) -> None:
    """Reddit OAuth 向导"""
    if action == "wizard":
        from radar.auth.strategies.reddit import RedditOAuthWizard
        wizard = RedditOAuthWizard()
        creds = await wizard.harvest()
        if creds:
            console.print(
                "\n[bold green]下一步：[/] 将凭证写入 .env 文件：\n"
                f"  [cyan]REDDIT_CLIENT_ID={creds['client_id']}[/]\n"
                f"  [cyan]REDDIT_CLIENT_SECRET={creds['client_secret']}[/]\n"
                "然后重启 radar 服务即可生效。"
            )
    elif action == "status":
        from radar.config import settings
        from radar.sources.reddit.client import RedditClient
        try:
            async with RedditClient(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
            ) as client:
                ok = await client.health_check()
            if ok:
                mode = "OAuth" if settings.reddit_client_id else "公开 API"
                console.print(f"[green]✓[/] Reddit API 连通 ({mode})")
            else:
                console.print("[red]✗[/] Reddit API 不可达")
        except Exception as exc:
            console.print(f"[red]✗[/] Reddit 连接失败: {exc}")
    else:
        console.print(f"[red]未知 action: {action}[/]（支持：status / wizard）")
