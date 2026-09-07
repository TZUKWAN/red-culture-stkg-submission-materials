"""Shared normalization helpers for the final STKG pipeline.

The pipeline keeps machine-readable time ranges in ISO date fields and preserves
the precision of the source expression in ``time_value``. A year-only source is
displayed as ``YYYY年`` rather than being falsified as January. Month and day
sources use ``YYYY年M月`` for display; day precision remains in the ISO fields.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date


CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


@dataclass(frozen=True)
class NormalizedTime:
    time_value: str
    time_start: str
    time_end: str
    time_granularity: str
    risk_flags: list[str]


def clean_text(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def cn_year_to_int(value: str) -> int | None:
    if not value or any(ch not in CN_DIGITS for ch in value):
        return None
    if len(value) != 4:
        return None
    return int("".join(str(CN_DIGITS[ch]) for ch in value))


def cn_num_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if value.startswith("十"):
        tail = value[1:]
        return 10 + (CN_DIGITS.get(tail, 0) if tail else 0)
    if "十" in value:
        head, tail = value.split("十", 1)
        tens = CN_DIGITS.get(head, 0)
        ones = CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    if len(value) == 1:
        return CN_DIGITS.get(value)
    return None


def clamp_date(year: int, month: int, day: int) -> str:
    month = max(1, min(12, month))
    last_day = calendar.monthrange(year, month)[1]
    day = max(1, min(last_day, day))
    return f"{year:04d}-{month:02d}-{day:02d}"


def month_end(year: int, month: int) -> str:
    return clamp_date(year, month, calendar.monthrange(year, month)[1])


def normalize_stage_range(value: str) -> NormalizedTime | None:
    value = clean_text(value)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s*(?:至|-|—|~)\s*(\d{4})-(\d{2})-(\d{2})$", value)
    if not m:
        return None
    y1, m1, d1, y2, m2, d2 = [int(x) for x in m.groups()]
    try:
        start = date(y1, m1, d1).isoformat()
        end = date(y2, m2, d2).isoformat()
    except ValueError:
        return None
    if start > end:
        return None
    display = f"{y1}年{m1}月" if (y1, m1) == (y2, m2) else f"{y1}年{m1}月-{y2}年{m2}月"
    granularity = "day" if start == end else "period"
    risks = ["time_day_collapsed_to_month_display"] if start == end else []
    return NormalizedTime(display, start, end, granularity, risks)


def normalize_text_range(value: str) -> NormalizedTime | None:
    text = clean_text(value).replace("元月", "1月")
    year = r"([一二三四五六七八九零〇○]{4}|\d{4})"
    month = r"([一二三四五六七八九十两\d]{1,3})"
    pattern = rf"{year}年(?:\s*{month}月)?\s*(?:至|到|-|—|~)\s*{year}年(?:\s*{month}月)?"
    match = re.search(pattern, text)
    if not match:
        match = re.search(r"(\d{4})[-/.](\d{1,2})\s*(?:至|到|-|—|~)\s*(\d{4})[-/.](\d{1,2})", text)
        if not match:
            return None
        y1, m1, y2, m2 = (int(part) for part in match.groups())
        if not (1 <= m1 <= 12 and 1 <= m2 <= 12):
            return None
        start = f"{y1:04d}-{m1:02d}-01"
        end = month_end(y2, m2)
        if start > end:
            return None
        if (y1, m1) == (y2, m2):
            return NormalizedTime(f"{y1}年{m1}月", start, end, "month", [])
        return NormalizedTime(f"{y1}年{m1}月-{y2}年{m2}月", start, end, "period", [])

    raw_y1, raw_m1, raw_y2, raw_m2 = match.groups()
    y1 = int(raw_y1) if raw_y1.isdigit() else cn_year_to_int(raw_y1)
    y2 = int(raw_y2) if raw_y2.isdigit() else cn_year_to_int(raw_y2)
    m1 = cn_num_to_int(raw_m1) if raw_m1 else None
    m2 = cn_num_to_int(raw_m2) if raw_m2 else None
    if not y1 or not y2 or not (1800 <= y1 <= 2100 and 1800 <= y2 <= 2100):
        return None
    if (m1 is not None and not 1 <= m1 <= 12) or (m2 is not None and not 1 <= m2 <= 12):
        return None
    start = f"{y1:04d}-{m1:02d}-01" if m1 else f"{y1:04d}-01-01"
    end = month_end(y2, m2) if m2 else f"{y2:04d}-12-31"
    if start > end:
        return None
    display_start = f"{y1}年{m1}月" if m1 else f"{y1}年"
    display_end = f"{y2}年{m2}月" if m2 else f"{y2}年"
    risks = [] if m1 is not None and m2 is not None else ["time_range_year_precision"]
    if y1 == y2 and m1 == m2:
        return NormalizedTime(
            display_start,
            start,
            end,
            "month" if m1 is not None else "year",
            risks,
        )
    return NormalizedTime(f"{display_start}-{display_end}", start, end, "period", risks)


def normalize_decade_expression(value: str) -> NormalizedTime | None:
    text = clean_text(value)
    match = re.search(r"(?:(\d{2})世纪(\d{2})|((?:18|19|20)\d{2}))年代(起|以来|至今)?", text)
    if not match:
        return None
    if match.group(3):
        year = int(match.group(3))
    else:
        year = (int(match.group(1)) - 1) * 100 + int(match.group(2))
    year = year - year % 10
    if not 1800 <= year <= 2100:
        return None
    start = f"{year:04d}-01-01"
    if match.group(4):
        return NormalizedTime(
            f"{year}年", start, "", "period", ["open_ended_decade_start"]
        )
    end_year = year + 9
    return NormalizedTime(
        f"{year}年-{end_year}年", start, f"{end_year:04d}-12-31",
        "period", ["time_decade_precision"],
    )


def extract_first_time(value: str) -> tuple[int, int | None, int | None] | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("元月", "1月")

    m = re.search(r"(\d{4})[-/\.](\d{1,2})(?:[-/\.](\d{1,2}))?", text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None

    m = re.search(r"([一二三四五六七八九零〇○]{4}|\d{4})年\s*([一二三四五六七八九十两\d]{1,3})月(?:\s*([一二三四五六七八九十两\d]{1,3})[日号])?", text)
    if m:
        year = int(m.group(1)) if m.group(1).isdigit() else cn_year_to_int(m.group(1))
        month = cn_num_to_int(m.group(2))
        day = cn_num_to_int(m.group(3)) if m.group(3) else None
        if year and month:
            return year, month, day

    m = re.search(r"([一二三四五六七八九零〇○]{4}|\d{4})年", text)
    if m:
        year = int(m.group(1)) if m.group(1).isdigit() else cn_year_to_int(m.group(1))
        if year:
            return year, None, None
    return None


def normalize_time_fields(
    time_value: object = "",
    time_start: object = "",
    time_end: object = "",
    time_granularity: object = "",
) -> NormalizedTime:
    risks: list[str] = []
    raw_value = clean_text(time_value)
    raw_start = clean_text(time_start)
    raw_end = clean_text(time_end)
    raw_granularity = clean_text(time_granularity)

    stage = (
        normalize_stage_range(raw_value)
        or normalize_text_range(raw_value)
        or normalize_decade_expression(raw_value)
    )
    if stage:
        return stage

    parsed = extract_first_time(raw_value)
    if not parsed:
        stage = (
            normalize_stage_range(f"{raw_start}-{raw_end}" if raw_start and raw_end else "")
            or normalize_text_range(f"{raw_start}-{raw_end}" if raw_start and raw_end else "")
        )
        if stage:
            return stage
        parsed = extract_first_time(raw_start)
    if not parsed and raw_end:
        parsed = extract_first_time(raw_end)
    if not parsed:
        return NormalizedTime("", "", "", raw_granularity if raw_granularity in {"unknown", ""} else "unknown", ["time_missing"])

    year, month, day = parsed
    if not (1800 <= year <= 2100):
        return NormalizedTime("", "", "", "unknown", ["time_year_out_of_range"])

    if month is None:
        start = f"{year:04d}-01-01"
        end = f"{year:04d}-12-31"
        return NormalizedTime(f"{year}年", start, end, "year", risks)

    if not 1 <= month <= 12:
        return NormalizedTime("", "", "", "unknown", ["time_month_out_of_range"])
    if day is None:
        start = f"{year:04d}-{month:02d}-01"
        end = month_end(year, month)
        granularity = "month"
    else:
        try:
            start = date(year, month, day).isoformat()
        except ValueError:
            return NormalizedTime("", "", "", "unknown", ["time_day_out_of_range"])
        end = start
        granularity = "day"
        risks.append("time_day_collapsed_to_month_display")
    return NormalizedTime(f"{year}年{month}月", start, end, granularity, risks)


def normalize_list_json(value: object) -> str:
    import json

    if isinstance(value, list):
        items = [clean_text(x) for x in value if clean_text(x)]
    else:
        text = clean_text(value)
        if not text:
            items = []
        else:
            try:
                parsed = json.loads(text)
                items = [clean_text(x) for x in parsed] if isinstance(parsed, list) else [text]
            except Exception:
                items = [x.strip() for x in re.split(r"[,;；、\n]+", text) if x.strip()]
    return json.dumps(items, ensure_ascii=False)
