"""Token 管理向导（S2/S3 实现后补充具体逻辑）"""
from __future__ import annotations

from rich.console import Console

console = Console()


async def run_wizard(source: str, action: str = "status") -> None:
    """交互式 Token 管理（stub，S2/S3 后实现）"""
    console.print(f"[yellow]Token 向导：source={source} action={action}[/]")
    console.print("💡 提示：S2（GitHub）和 S3（Reddit）完成后，此命令将引导你完成 Token 配置")
