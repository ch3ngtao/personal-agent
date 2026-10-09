"""统一的时间来源。

大模型自己没有时钟，凡是给模型「现在是几点」的信息，都得由服务端注入。
这里统一取时间，避免各处各写一遍 ``datetime.now().astimezone()``：

``astimezone()`` 取的是运行环境的本地时区，而 Docker 基础镜像默认是 UTC——容器里会
比北京时间早 8 小时，凌晨那段时间连日期都是错的。所以这里显式按配置的 ``TIMEZONE`` 取，
不依赖容器环境变量。
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


@lru_cache
def app_timezone() -> ZoneInfo | None:
    """配置的时区；名字不合法或缺少时区数据时返回 None（退回本地时区）。"""
    name = (get_settings().timezone or "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("无法识别时区 %r，改用运行环境的本地时区", name)
        return None


def now() -> datetime:
    """当前时间（带时区）。"""
    zone = app_timezone()
    return datetime.now(zone) if zone else datetime.now().astimezone()


def weekday_cn(moment: datetime) -> str:
    return WEEKDAYS[moment.weekday()]


def describe(moment: datetime | None = None, *, with_time: bool = True) -> str:
    """给人/给模型看的时间描述，例如 ``2026-10-09 18:05（星期五）``。"""
    moment = moment or now()
    stamp = f"{moment:%Y-%m-%d %H:%M}" if with_time else f"{moment:%Y-%m-%d}"
    return f"{stamp}（{weekday_cn(moment)}）"
