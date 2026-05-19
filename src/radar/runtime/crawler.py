"""爬取任务分发器（S2/S3 实现后正式接入）"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def run_crawl(source: str = "all", dry_run: bool = False) -> dict:
    """
    分发到各源的 crawl 函数。
    S2 实现 github，S3 实现 reddit，这里负责路由。
    """
    targets = _resolve_targets(source)
    results: dict[str, dict] = {}

    for target in targets:
        if dry_run:
            logger.info("dry_run 跳过实际抓取", source=target)
            results[target] = {"status": "dry_run"}
            continue

        try:
            result = await _dispatch(target)
            results[target] = result
        except NotImplementedError:
            logger.warning("数据源尚未实现", source=target)
            results[target] = {"status": "not_implemented"}
        except Exception as exc:
            logger.exception("抓取失败", source=target, error=str(exc))
            results[target] = {"status": "error", "error": str(exc)}

    return results


def _resolve_targets(source: str) -> list[str]:
    if source == "all":
        return ["github", "reddit"]
    return [source]


async def _dispatch(source: str) -> dict:
    if source == "github":
        from radar.sources.github.crawler import crawl_github
        return await crawl_github()
    if source == "reddit":
        from radar.sources.reddit.crawler import crawl_reddit
        return await crawl_reddit()
    raise NotImplementedError(f"未实现的数据源: {source}")
