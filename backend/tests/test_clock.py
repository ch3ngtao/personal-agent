"""统一时间来源的测试：时区可配、按分钟输出、坏配置能兜底。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core import clock
from app.core.config import Settings, get_settings


def test_describe_formats_date_time_and_weekday() -> None:
    moment = datetime(2026, 10, 9, 18, 5, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert clock.describe(moment) == "2026-10-09 18:05（星期五）"
    assert clock.describe(moment, with_time=False) == "2026-10-09（星期五）"


def test_now_uses_configured_timezone() -> None:
    settings = get_settings()

    moment = clock.now()

    assert moment.tzinfo is not None
    assert str(moment.tzinfo) == settings.timezone


def test_invalid_timezone_falls_back_to_local(monkeypatch) -> None:  # noqa: ANN001
    clock.app_timezone.cache_clear()
    monkeypatch.setattr("app.core.clock.get_settings", lambda: Settings(timezone="Not/AZone"))
    try:
        assert clock.app_timezone() is None
        # 兜底后仍然要能拿到带时区的时间，不能抛异常
        assert clock.now().tzinfo is not None
    finally:
        clock.app_timezone.cache_clear()


def test_weekday_is_chinese() -> None:
    monday = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert clock.weekday_cn(monday) == "星期一"
