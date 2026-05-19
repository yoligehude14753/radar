"""报告渲染器入口（S6/S7 实现后完整替换）"""
from __future__ import annotations


async def render_report(template: str) -> dict:
    """
    渲染指定模板的报告。
    S6（projects）和 S7（communities）实现后此函数路由到对应渲染逻辑。
    """
    if template == "projects":
        from radar.outputs.projects import render_projects_report
        return await render_projects_report()
    elif template == "communities":
        from radar.outputs.communities import render_communities_report
        return await render_communities_report()
    else:
        raise ValueError(f"未知模板: {template}（支持：projects / communities）")
