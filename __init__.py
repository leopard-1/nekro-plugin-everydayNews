"""Daily news plugin powered by RavelloH/EverydayNews."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

import httpx
from pydantic import Field

from nekro_agent.api.plugin import (
    Arg,
    CmdCtl,
    CommandExecutionContext,
    CommandPermission,
    ConfigBase,
    NekroPlugin,
    SandboxMethodType,
)
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.services.command.schemas import CommandResponse

plugin = NekroPlugin(
    name="每日新闻",
    module_name="daily_news",
    description="从 EverydayNews 获取每日 60 秒新闻，支持最新、指定日期和关键词搜索。",
    version="0.1.0",
    author="Sakuralis",
    url="https://github.com/Leopard-1/nekro-plugin-everydayNews",
    sleep_brief="用户询问每日新闻、某天新闻、新闻关键词搜索时激活。",
)


@plugin.mount_config()
class DailyNewsConfig(ConfigBase):
    BASE_URL: str = Field(
        default="https://news.ravelloh.top",
        title="EverydayNews API 地址",
        description="可切换为 https://ravelloh.github.io/EverydayNews。",
    )
    SEARCH_DAYS: int = Field(
        default=30,
        title="关键词搜索天数",
        description="关键词搜索时，从最新日期向前扫描的天数。",
    )
    SEARCH_RESULT_LIMIT: int = Field(
        default=10,
        title="关键词搜索结果数",
        description="关键词搜索最多返回多少条新闻。",
    )
    REQUEST_TIMEOUT: float = Field(
        default=12.0,
        title="请求超时秒数",
        description="访问 EverydayNews API 的超时时间。",
    )
    SHOW_SOURCE: bool = Field(
        default=False,
        title="显示来源链接",
        description="开启后在文本末尾显示 EverydayNews 来源地址。",
    )


config = plugin.get_config(DailyNewsConfig)


@dataclass(frozen=True)
class NewsData:
    date: str
    content: list[str]


def _base_url() -> str:
    return config.BASE_URL.rstrip("/")


def _normalize_date(date_text: str) -> str:
    """Normalize YYYY-MM-DD, YYYY/MM/DD or YYYYMMDD into YYYY/MM/DD."""
    raw = date_text.strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 8:
        raise ValueError("日期格式应为 YYYY-MM-DD、YYYY/MM/DD 或 YYYYMMDD")
    parsed = datetime.strptime(digits, "%Y%m%d")
    return parsed.strftime("%Y/%m/%d")


def _date_url(date_text: str) -> str:
    year, month, day = date_text.split("/")
    return f"{_base_url()}/data/{year}/{month}/{day}.json"


async def _fetch_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _parse_news(data: dict) -> NewsData:
    date = str(data.get("date", "")).strip()
    content = data.get("content", [])
    if not date or not isinstance(content, list):
        raise ValueError("新闻数据格式不正确")
    items = [str(item).strip() for item in content if str(item).strip()]
    if not items:
        raise ValueError("新闻内容为空")
    return NewsData(date=date, content=items)


async def _fetch_latest_news() -> NewsData:
    return _parse_news(await _fetch_json(f"{_base_url()}/latest.json"))


async def _fetch_news_by_date(date_text: str) -> NewsData:
    normalized = _normalize_date(date_text)
    return _parse_news(await _fetch_json(_date_url(normalized)))


def _format_news(news: NewsData, *, title: str = "每日新闻") -> str:
    lines = [f"{title} | {news.date}", ""]
    lines.extend(f"{index}. {item}" for index, item in enumerate(news.content, start=1))
    if config.SHOW_SOURCE:
        lines.append("")
        lines.append(f"来源: {_base_url()}")
    return "\n".join(lines)


async def _send_news(ctx: AgentCtx, news: NewsData, *, title: str = "每日新闻") -> str:
    text = _format_news(news, title=title)
    await ctx.send_text(text)
    return text


async def _search_news(keyword: str, days: int | None = None, limit: int | None = None) -> list[tuple[str, str]]:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("关键词不能为空")

    latest = await _fetch_latest_news()
    start = datetime.strptime(latest.date, "%Y/%m/%d")
    scan_days = max(1, min(days or config.SEARCH_DAYS, 365))
    result_limit = max(1, min(limit or config.SEARCH_RESULT_LIMIT, 50))
    results: list[tuple[str, str]] = []

    for offset in range(scan_days):
        day = start - timedelta(days=offset)
        date_text = day.strftime("%Y/%m/%d")
        try:
            news = latest if offset == 0 else await _fetch_news_by_date(date_text)
        except Exception as e:
            plugin.logger.debug(f"跳过无法获取的新闻日期 {date_text}: {e}")
            continue
        for item in news.content:
            if keyword.lower() in item.lower():
                results.append((news.date, item))
                if len(results) >= result_limit:
                    return results
    return results


def _format_search_results(keyword: str, results: list[tuple[str, str]], days: int) -> str:
    if not results:
        return f"未在最近 {days} 天的每日新闻中找到关键词: {keyword}"
    lines = [f"每日新闻搜索: {keyword}", f"范围: 最近 {days} 天", ""]
    for index, (date_text, item) in enumerate(results, start=1):
        lines.append(f"{index}. [{date_text}] {item}")
    if config.SHOW_SOURCE:
        lines.append("")
        lines.append(f"来源: {_base_url()}")
    return "\n".join(lines)


@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="获取每日新闻",
    description="获取最新或指定日期的每日新闻，并以纯文本发送到当前聊天。",
)
async def get_daily_news(ctx: AgentCtx, date: str = "") -> str:
    """获取并推送每日新闻。

    Args:
        date: 可选日期，支持 YYYY-MM-DD、YYYY/MM/DD、YYYYMMDD。留空表示最新新闻。

    Returns:
        str: 已发送的新闻文本。

    Example:
        get_daily_news()
        get_daily_news("2025-01-01")
    """
    news = await (_fetch_news_by_date(date) if date.strip() else _fetch_latest_news())
    return await _send_news(ctx, news)


@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="搜索每日新闻",
    description="从最新新闻向前扫描一段时间，搜索包含关键词的每日新闻，并以纯文本发送。",
)
async def search_daily_news(ctx: AgentCtx, keyword: str, days: int = 0) -> str:
    """搜索并推送关键词相关新闻。

    Args:
        keyword: 要搜索的关键词。
        days: 从最新日期向前搜索的天数；0 表示使用插件配置。

    Returns:
        str: 搜索结果文本。

    Example:
        search_daily_news("AI")
        search_daily_news("黄金", 60)
    """
    scan_days = days or config.SEARCH_DAYS
    results = await _search_news(keyword, days=scan_days)
    message = _format_search_results(keyword, results, scan_days)
    await ctx.send_text(message)
    return message


@plugin.mount_command(
    name="daily_news",
    description="获取每日新闻，支持最新、指定日期或关键词搜索。",
    aliases=["每日新闻", "新闻"],
    usage="/daily_news [日期] 或 /daily_news search <关键词> [天数]",
    permission=CommandPermission.PUBLIC,
    category="每日新闻",
    tags=["news", "daily", "search"],
)
async def daily_news_cmd(
    context: CommandExecutionContext,
    query: Annotated[str, Arg("日期、关键词，或 search 子命令", positional=True, greedy=True)] = "",
) -> CommandResponse:
    query = query.strip()
    try:
        if query.lower().startswith(("search ", "搜索 ")):
            parts = query.split()
            keyword = parts[1] if len(parts) >= 2 else ""
            days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else config.SEARCH_DAYS
            results = await _search_news(keyword, days=days)
            return CmdCtl.success(_format_search_results(keyword, results, days))

        news = await (_fetch_news_by_date(query) if query else _fetch_latest_news())
        return CmdCtl.success(_format_news(news))
    except Exception as e:
        plugin.logger.exception(f"每日新闻命令执行失败: {e}")
        return CmdCtl.failed(f"每日新闻获取失败: {e}")
