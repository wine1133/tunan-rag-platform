"""时间工具。

Tortoise 要求写进 DatetimeField 的值带时区信息，直接用 datetime.now()
得到的是不带时区的裸时间，写库时会告警。全项目记录开始时间、结束时间、
耗时都用这里的两个函数。

时区必须和 settings.py 里配的 timezone 一致，都是东八区。
两边不一致时，取出来的时间会整体偏 8 小时：页面上显示的"创建时间"
比实际早八个钟头，跨零点时连日期都是错的。
"""

from datetime import datetime, timedelta, timezone

# 东八区。和 settings.TORTOISE_ORM 里的 timezone 配置保持一致
CST = timezone(timedelta(hours=8))


def now() -> datetime:
    """带时区的当前时间，可直接写进 DatetimeField。"""
    return datetime.now(CST)


def cost_millis(started: datetime) -> int:
    """从 started 到现在经过的毫秒数，写进各类记录表的 cost_millis 列。"""
    return int((now() - started).total_seconds() * 1000)
