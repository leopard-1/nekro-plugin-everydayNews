"""Daily news plugin powered by RavelloH/EverydayNews."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field

from nekro_agent.api.plugin import (
    Arg,
    CmdCtl,
    CommandExecutionContext,
    CommandPermission,
    ConfigBase,
    ExtraField,
    NekroPlugin,
    SandboxMethodType,
)
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.services.command.schemas import CommandResponse
from nekro_agent.services.timer.timer_service import timer_service

plugin = NekroPlugin(
    name="每日新闻",
    module_name="daily_news",
    description="从 EverydayNews 获取每日 60 秒新闻，支持最新、指定日期、关键词搜索和每日定时推送。",
    version="0.3.1",
    author="Sakuralis",
    url="https://github.com/Leopard-1/nekro-plugin-everydayNews",
    sleep_brief="用户询问每日新闻、某天新闻、新闻关键词搜索，或需要每日定时推送新闻时激活。",
)

JOB_TITLE = "每日新闻定时推送"
_scheduled_task_ids: dict[str, str] = {}


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
        description="关键词搜索时，从系统日期向前扫描的天数。",
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
    DAILY_PUSH_ENABLED: bool = Field(
        default=False,
        title="启用每日定时推送",
        description="开启后会用 Nekro-Agent 本地定时器在指定时间直接推送新闻。",
    )
    DAILY_PUSH_TIME: str = Field(
        default="08:00",
        title="每日推送时间",
        description="每天推送新闻的本机时间，格式 HH:MM，例如 08:00 或 21:30。",
        json_schema_extra=ExtraField(placeholder="08:00").model_dump(),
    )
    DAILY_PUSH_TIMEZONE: str = Field(
        default="Asia/Shanghai",
        title="每日推送时区",
        description="用于读取系统当前日期和计算每日推送时间的 IANA 时区，例如 Asia/Shanghai。",
        json_schema_extra=ExtraField(placeholder="Asia/Shanghai").model_dump(),
    )
    DAILY_PUSH_CHAT_KEYS: list[str] = Field(
        default_factory=list,
        title="每日推送目标群聊",
        description="需要推送新闻的 chat_key 列表，例如 onebot_v11-group_123456789。",
        json_schema_extra=ExtraField(sub_item_name="chat_key").model_dump(),
    )


config = plugin.get_config(DailyNewsConfig)


@dataclass(frozen=True)
class NewsData:
    date: str
    content: list[str]


def _base_url() -> str:
    return config.BASE_URL.rstrip("/")


def _timezone() -> ZoneInfo:
    timezone = config.DAILY_PUSH_TIMEZONE.strip() or "Asia/Shanghai"
    return ZoneInfo(timezone)


def _system_today() -> str:
    return datetime.now(_timezone()).strftime("%Y/%m/%d")


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


async def _fetch_system_today_news() -> NewsData:
    """Fetch news by local system date, falling back to latest if today's file is not published yet."""
    today = _system_today()
    try:
        return await _fetch_news_by_date(today)
    except Exception as e:
        plugin.logger.warning(f"系统日期 {today} 的新闻暂不可用，回退到 latest.json: {e}")
        return await _fetch_latest_news()


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


def _parse_push_time() -> tuple[int, int]:
    value = config.DAILY_PUSH_TIME.strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", value):
        raise ValueError("每日推送时间格式应为 HH:MM")
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("每日推送时间应在 00:00 到 23:59 之间")
    return hour, minute


def _next_push_timestamp() -> int:
    tz = _timezone()
    now = datetime.now(tz)
    hour, minute = _parse_push_time()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return int(next_run.timestamp())


def _target_chat_keys() -> list[str]:
    seen: set[str] = set()
    targets: list[str] = []
    for chat_key in config.DAILY_PUSH_CHAT_KEYS:
        value = chat_key.strip()
        if value and value not in seen:
            seen.add(value)
            targets.append(value)
    return targets


async def _push_latest_news_to_chat(chat_key: str, text: str) -> None:
    ctx = await AgentCtx.create_by_chat_key(chat_key)
    await ctx.ms.send_text(chat_key, text, ctx, record=False)


async def _push_today_news_to_configured_chats() -> int:
    targets = _target_chat_keys()
    if not targets:
        raise ValueError("请先在插件配置里填写 DAILY_PUSH_CHAT_KEYS")

    news = await _fetch_system_today_news()
    text = _format_news(news)
    sent_count = 0
    for chat_key in targets:
        await _push_latest_news_to_chat(chat_key, text)
        sent_count += 1
        plugin.logger.info(f"每日新闻已推送到 {chat_key}: {news.date}")
    return sent_count


async def _daily_push_callback(chat_key: str) -> None:
    try:
        news = await _fetch_system_today_news()
        text = _format_news(news)
        await _push_latest_news_to_chat(chat_key, text)
        plugin.logger.info(f"每日新闻定时推送成功: chat_key={chat_key}, date={news.date}")
    except Exception as e:
        plugin.logger.exception(f"每日新闻定时推送失败: chat_key={chat_key}, error={e}")
    finally:
        if config.DAILY_PUSH_ENABLED and chat_key in _target_chat_keys():
            await _schedule_chat_daily_push(chat_key)


async def _delete_scheduled_tasks() -> None:
    for chat_key, task_id in list(_scheduled_task_ids.items()):
        try:
            await timer_service.delete_timer_by_id(task_id)
            plugin.logger.info(f"已删除每日新闻本地定时器: chat_key={chat_key}, task_id={task_id}")
        except Exception as e:
            plugin.logger.warning(f"删除每日新闻本地定时器失败: chat_key={chat_key}, task_id={task_id}, error={e}")
    _scheduled_task_ids.clear()


async def _schedule_chat_daily_push(chat_key: str) -> None:
    old_task_id = _scheduled_task_ids.pop(chat_key, "")
    if old_task_id:
        await timer_service.delete_timer_by_id(old_task_id)

    trigger_time = _next_push_timestamp()
    event_desc = f"{JOB_TITLE}: {chat_key}"

    async def callback() -> None:
        await _daily_push_callback(chat_key)

    ok = await timer_service.set_timer(
        chat_key=chat_key,
        trigger_time=trigger_time,
        event_desc=event_desc,
        silent=True,
        callback=callback,
    )
    if not ok:
        raise RuntimeError(f"设置每日新闻本地定时器失败: {chat_key}")

    task = timer_service.get_timers(chat_key)[-1]
    _scheduled_task_ids[chat_key] = task.task_id
    next_run_text = datetime.fromtimestamp(trigger_time, _timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")
    plugin.logger.info(f"已设置每日新闻本地定时器: chat_key={chat_key}, task_id={task.task_id}, next={next_run_text}")


async def _sync_daily_push_schedule() -> dict[str, str]:
    await _delete_scheduled_tasks()

    if not config.DAILY_PUSH_ENABLED:
        plugin.logger.info("每日新闻定时推送未启用")
        return {}

    targets = _target_chat_keys()
    if not targets:
        plugin.logger.warning("每日新闻定时推送已启用，但 DAILY_PUSH_CHAT_KEYS 为空")
        return {}

    for chat_key in targets:
        await _schedule_chat_daily_push(chat_key)
    return dict(_scheduled_task_ids)


@plugin.mount_init_method()
async def init() -> None:
    await _sync_daily_push_schedule()


@plugin.mount_cleanup_method()
async def cleanup() -> None:
    await _delete_scheduled_tasks()


async def _search_news(keyword: str, days: int | None = None, limit: int | None = None) -> list[tuple[str, str]]:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("关键词不能为空")

    start = datetime.strptime(_system_today(), "%Y/%m/%d")
    scan_days = max(1, min(days or config.SEARCH_DAYS, 365))
    result_limit = max(1, min(limit or config.SEARCH_RESULT_LIMIT, 50))
    results: list[tuple[str, str]] = []

    for offset in range(scan_days):
        day = start - timedelta(days=offset)
        date_text = day.strftime("%Y/%m/%d")
        try:
            news = await _fetch_news_by_date(date_text)
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
    description="获取系统日期或指定日期的每日新闻，并以纯文本发送到当前聊天。",
)
async def get_daily_news(ctx: AgentCtx, date: str = "") -> str:
    """获取并推送每日新闻。

    Args:
        date: 可选日期，支持 YYYY-MM-DD、YYYY/MM/DD、YYYYMMDD。留空表示按系统日期获取。

    Returns:
        str: 已发送的新闻文本。
    """
    news = await (_fetch_news_by_date(date) if date.strip() else _fetch_system_today_news())
    return await _send_news(ctx, news)


@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="搜索每日新闻",
    description="从系统日期向前扫描一段时间，搜索包含关键词的每日新闻，并以纯文本发送。",
)
async def search_daily_news(ctx: AgentCtx, keyword: str, days: int = 0) -> str:
    """搜索并推送关键词相关新闻。

    Args:
        keyword: 要搜索的关键词。
        days: 从系统日期向前搜索的天数，0 表示使用插件配置。

    Returns:
        str: 搜索结果文本。
    """
    scan_days = days or config.SEARCH_DAYS
    results = await _search_news(keyword, days=scan_days)
    message = _format_search_results(keyword, results, scan_days)
    await ctx.send_text(message)
    return message


@plugin.mount_command(
    name="daily_news",
    description="获取每日新闻，支持系统日期、指定日期或关键词搜索。",
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

        news = await (_fetch_news_by_date(query) if query else _fetch_system_today_news())
        return CmdCtl.success(_format_news(news))
    except Exception as e:
        plugin.logger.exception(f"每日新闻命令执行失败: {e}")
        return CmdCtl.failed(f"每日新闻获取失败: {e}")


@plugin.mount_command(
    name="daily_news_sync_schedule",
    description="按当前插件配置同步每日新闻本地定时推送任务。",
    aliases=[],
    usage="/daily_news_sync_schedule",
    permission=CommandPermission.SUPER_USER,
    category="每日新闻",
    tags=["news", "daily", "schedule"],
)
async def daily_news_sync_schedule_cmd(context: CommandExecutionContext) -> CommandResponse:
    try:
        jobs = await _sync_daily_push_schedule()
        if not config.DAILY_PUSH_ENABLED:
            return CmdCtl.success("每日新闻定时推送已关闭，旧任务已清理。")
        if not jobs:
            return CmdCtl.failed("未创建定时任务，请检查 DAILY_PUSH_CHAT_KEYS 是否已填写。")
        next_run = datetime.fromtimestamp(_next_push_timestamp(), _timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")
        detail = "\n".join(f"- {chat_key}: {task_id}" for chat_key, task_id in jobs.items())
        return CmdCtl.success(f"每日新闻定时推送已同步。\n下次触发: {next_run}\n任务:\n{detail}")
    except Exception as e:
        plugin.logger.exception(f"每日新闻定时任务同步失败: {e}")
        return CmdCtl.failed(f"每日新闻定时任务同步失败: {e}")


@plugin.mount_command(
    name="daily_news_push_now",
    description="立即向配置的目标群聊推送一次系统日期的每日新闻。",
    aliases=[],
    usage="/daily_news_push_now",
    permission=CommandPermission.SUPER_USER,
    category="每日新闻",
    tags=["news", "daily", "push"],
)
async def daily_news_push_now_cmd(context: CommandExecutionContext) -> CommandResponse:
    try:
        sent_count = await _push_today_news_to_configured_chats()
        return CmdCtl.success(f"已执行每日新闻手动推送，共发送 {sent_count} 个目标。")
    except Exception as e:
        plugin.logger.exception(f"每日新闻手动推送失败: {e}")
        return CmdCtl.failed(f"每日新闻手动推送失败: {e}")
