"""Excel 日期序列轉換｜序列數字 <-> ISO 字串，parser 與 renderer 共用同一份規則。

共用是必要的：如果兩邊各自實作，round-trip 只會證明兩份實作剛好一致，
而不是證明轉換正確。這裡是唯一真相源。

兩個容易錯的地方都在這裡處理：
1. 1900 制有一個不存在的 1900-02-29（序列 60）——Lotus 1-2-3 相容性遺留的閏年 bug。
2. 1904 制的原點不同，整整差 1462 天。把 1904 制的檔案當 1900 制解讀，所有日期會錯四年多。

io: in=序列數字或 ISO 字串; out=另一種表示
依賴: 標準函式庫 datetime
"""

from __future__ import annotations

import datetime as dt

from docengine.core.errors import ParseError

#: 1900 制：序列 1 = 1900-01-01。因為有幽靈的 1900-02-29，序列 61 之後才對得上 1899-12-30 原點。
_EPOCH_1900_BEFORE_BUG = dt.date(1899, 12, 31)
_EPOCH_1900_AFTER_BUG = dt.date(1899, 12, 30)
_EPOCH_1904 = dt.date(1904, 1, 1)

#: 1900 制裡不存在的那一天。碰到它必須明講，不能靜默給一個錯誤日期。
PHANTOM_SERIAL = 60


def serial_to_iso(serial: float, date1904: bool = False) -> str:
    """序列數字轉 ISO 8601。有小數部分就回 datetime，否則回 date。"""
    days = int(serial)
    fraction = float(serial) - days

    if date1904:
        base = _EPOCH_1904 + dt.timedelta(days=days)
    else:
        if days == PHANTOM_SERIAL:
            raise ParseError(
                "序列 60 在 1900 制對應到不存在的 1900-02-29（Excel 的閏年相容性 bug）",
                serial=serial,
            )
        if days < PHANTOM_SERIAL:
            base = _EPOCH_1900_BEFORE_BUG + dt.timedelta(days=days)
        else:
            base = _EPOCH_1900_AFTER_BUG + dt.timedelta(days=days)

    if abs(fraction) < 1e-9:
        return base.isoformat()
    seconds = round(fraction * 86400)
    return (dt.datetime.combine(base, dt.time()) + dt.timedelta(seconds=seconds)).isoformat()


def iso_to_serial(value: str, date1904: bool = False) -> float | int:
    """ISO 8601 轉序列數字。``serial_to_iso`` 的反函式。"""
    text = value.strip()
    try:
        if "T" in text:
            moment = dt.datetime.fromisoformat(text)
            day, time_part = moment.date(), moment.time()
        else:
            day, time_part = dt.date.fromisoformat(text), None
    except ValueError as exc:
        raise ParseError("不是合法的 ISO 日期或時間", value=value) from exc

    if date1904:
        days = (day - _EPOCH_1904).days
    else:
        days = (day - _EPOCH_1900_AFTER_BUG).days
        if days <= PHANTOM_SERIAL:
            days = (day - _EPOCH_1900_BEFORE_BUG).days

    if time_part is None:
        return days
    seconds = time_part.hour * 3600 + time_part.minute * 60 + time_part.second
    if seconds == 0:
        return days
    return days + seconds / 86400


__all__ = ["serial_to_iso", "iso_to_serial", "PHANTOM_SERIAL"]
