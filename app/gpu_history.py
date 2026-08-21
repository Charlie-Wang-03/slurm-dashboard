"""GPU history reads and aggregation for the dashboard charts.

Reads collector data from data/gpu_history/gpu_history.jsonl and
aggregates it per user and time scale for the chart JSON API.

Two display modes:
- linear: data expanded in time order, continuous time labels
- overlay: data aligned by position within each period, labels are the
  position within the period (e.g. weekday, day-of-month, ISO week)

Time scales: day / week / month / year
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.config import DASHBOARD_DIR

HISTORY_DIR = DASHBOARD_DIR / "data" / "gpu_history"
HISTORY_FILE = HISTORY_DIR / "gpu_history.jsonl"


def _local_tz():
    """The server's local timezone (the dashboard has no fixed TZ)."""
    return datetime.now().astimezone().tzinfo

VALID_SCALES = ("day", "week", "month", "year")
VALID_MODES = ("linear", "overlay")

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_LABELS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── time parsing and data reading ─────────────────────────────────

def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp into a timezone-aware datetime.

    Handles any UTC offset, including the ``+08:00`` suffix written by
    v0.1.0 collectors (legacy data keeps working unchanged). Naive
    timestamps (no offset) are interpreted as server-local time.
    """
    ts_str = (ts_str or "").strip()
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return dt


def read_gpu_history(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Read GPU history records within the given time range.

    Args:
        start_time: inclusive start; None means unbounded.
        end_time: inclusive end; None means unbounded.

    Returns:
        Collector records sorted by time.
    """
    if not HISTORY_FILE.exists():
        return []

    records = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = _parse_timestamp(record.get("timestamp", ""))
                if ts is None:
                    continue
                if start_time and ts < start_time:
                    continue
                if end_time and ts > end_time:
                    continue
                records.append((ts, record))

        records.sort(key=lambda x: x[0])
        return [r for _, r in records]
    except OSError:
        return []


# ── time truncation and scale bounds ───────────────────────────────

def _truncate_time(dt: datetime, scale: str) -> datetime:
    """Truncate a timestamp to the bucket granularity of the scale.

    - day: 5-minute boundary
    - week / month: top of the hour
    - year: start of the day
    """
    if scale == "day":
        minute = (dt.minute // 5) * 5
        return dt.replace(minute=minute, second=0, microsecond=0)
    elif scale in ("week", "month"):
        return dt.replace(minute=0, second=0, microsecond=0)
    elif scale == "year":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


def _get_scale_bounds(
    scale: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> tuple:
    """Get the start, end and bucket granularity for a time scale.

    Returns:
        (start, end, bucket_delta)
    """
    now = datetime.now().astimezone()

    # default bounds when the caller did not specify start/end
    if start_time is None:
        if scale == "day":
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif scale == "week":
            start_time = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
        elif scale == "month":
            start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif scale == "year":
            start_time = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if end_time is None:
        end_time = now

    if scale == "day":
        bucket_delta = timedelta(minutes=5)
    elif scale == "week":
        bucket_delta = timedelta(hours=1)
    elif scale == "month":
        bucket_delta = timedelta(hours=1)
    elif scale == "year":
        bucket_delta = timedelta(days=1)
    else:
        bucket_delta = timedelta(minutes=5)

    return start_time, end_time, bucket_delta


# ── overlay-mode helpers ───────────────────────────────────────────

def _get_overlay_buckets(scale: str, lang: str = "en") -> tuple:
    """Return the bucket count and label function for overlay mode.

    Args:
        scale: day / week / month / year
        lang: label language — "zh" (Chinese) or "en" (English).

    Returns:
        (bucket_count: int, label_fn: callable)

    Label semantics:
    - day: 288 buckets, one every 5 minutes of the day
    - week: 7 buckets, one per weekday
    - month: 31 buckets, one per day of the month
    - year: 52 buckets, one per ISO week (ISO week 53 merges into 52)
    """
    if scale == "day":
        return 288, lambda i: f"{i // 12:02d}:{5 * (i % 12):02d}"
    elif scale == "week":
        labels = WEEKDAY_LABELS if lang == "zh" else WEEKDAY_LABELS_EN
        return 7, lambda i: labels[i]
    elif scale == "month":
        if lang == "zh":
            return 31, lambda i: f"{i + 1}日"
        return 31, lambda i: str(i + 1)
    elif scale == "year":
        if lang == "zh":
            return 52, lambda i: f"第{i + 1}周"
        return 52, lambda i: f"W{i + 1}"
    return 288, lambda i: f"{i // 12:02d}:{5 * (i % 12):02d}"


def _overlay_bucket_index(dt: datetime, scale: str) -> int:
    """Map a timestamp to its 0-based overlay bucket index.

    Mapping rules:
    - day: (hour*60+minute)//5 → 0..287
    - week: weekday() → Mon=0..Sun=6
    - month: day-1 → 0..30
    - year: ISO week-1 → 0..51 (53→52, avoids overflow)
    """
    if scale == "day":
        return (dt.hour * 60 + dt.minute) // 5
    elif scale == "week":
        return dt.weekday()
    elif scale == "month":
        return dt.day - 1
    elif scale == "year":
        week = dt.isocalendar()[1]
        return min(week - 1, 51)
    return (dt.hour * 60 + dt.minute) // 5


# ── date parameter parsing ─────────────────────────────────────────

def _parse_date_param(date_str: str, scale: str) -> datetime:
    """Parse a front-end date string for a scale as server-local time.

    Supported formats:
    - day: "2026-07-25" (ISO date)
    - week: "2026-W30" (ISO week)
    - month: "2026-07" (ISO month)
    - year: "2026" (plain year)
    """
    if scale == "day":
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    elif scale == "week":
        # format "2026-W30"
        date_str = date_str.strip()
        import re
        match = re.match(r"(\d{4})-W(\d{2})", date_str)
        if not match:
            raise ValueError(f"invalid week format: {date_str}, expected 2026-W30")
        year = int(match.group(1))
        week = int(match.group(2))
        # Jan 4 of the year always falls in week 1
        jan4 = datetime(year, 1, 4)
        start_of_week1 = jan4 - timedelta(days=jan4.weekday())
        dt = start_of_week1 + timedelta(weeks=week - 1)
    elif scale == "month":
        dt = datetime.strptime(date_str.strip(), "%Y-%m")
    elif scale == "year":
        dt = datetime(int(date_str.strip()), 1, 1)
    else:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    return dt.replace(tzinfo=_local_tz())


# ── aggregation entry points ───────────────────────────────────────

def _aggregate_linear(
    records: list,
    scale: str,
    start_time: datetime,
    end_time: datetime,
) -> Dict[str, Any]:
    """Linear aggregation: average per time bucket, in time order."""
    _, _, bucket_delta = _get_scale_bounds(scale, start_time, end_time)

    # build the time buckets
    buckets = []
    current = _truncate_time(start_time, scale)
    while current <= end_time:
        buckets.append(current)
        current += bucket_delta

    if not buckets:
        return _empty_result(scale)

    # per-user bucket accumulators
    user_bucket_data: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"memory_sum": 0.0, "util_sum": 0.0, "count": 0})
    )

    all_utilizations = []
    gpu_count = 0

    for record in records:
        ts = _parse_timestamp(record.get("timestamp", ""))
        if ts is None:
            continue
        if ts < start_time or ts > end_time:
            continue

        bucket_ts = _truncate_time(ts, scale)
        try:
            bucket_idx = buckets.index(bucket_ts)
        except ValueError:
            continue

        gpus = record.get("gpus", [])
        if gpus:
            gpu_count = max(gpu_count, len(gpus))

        for gpu in gpus:
            gpu_util = gpu.get("utilization_gpu", 0)
            all_utilizations.append(gpu_util)

            processes = gpu.get("processes", [])
            if processes:
                gpu_user_memory: Dict[str, float] = defaultdict(float)
                for proc in processes:
                    user = proc.get("user", "unknown")
                    mem = proc.get("used_memory_mb", 0)
                    gpu_user_memory[user] += mem

                for user, mem in gpu_user_memory.items():
                    user_bucket_data[user][bucket_idx]["memory_sum"] += mem
                    user_bucket_data[user][bucket_idx]["util_sum"] += gpu_util
                    user_bucket_data[user][bucket_idx]["count"] += 1

    # build the output
    timeline_labels = [b.strftime("%Y-%m-%d %H:%M") for b in buckets]
    users_data, final_user_memory = _build_user_series(
        user_bucket_data, len(buckets), mode="linear"
    )

    return _build_result(
        scale, "linear", timeline_labels, users_data, final_user_memory,
        all_utilizations, gpu_count,
    )


def _aggregate_overlay(
    records: list,
    scale: str,
    start_time: datetime,
    end_time: datetime,
    lang: str = "en",
) -> Dict[str, Any]:
    """Overlay aggregation: align records by position within the period.

    - memory (MB): SUM (total resource consumption over the window)
    - utilization (%): AVG (a sum is physically meaningless)
    """
    bucket_count, label_fn = _get_overlay_buckets(scale, lang=lang)

    # user -> bucket_idx -> {memory_sum, util_sum, count}
    user_bucket_data: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"memory_sum": 0.0, "util_sum": 0.0, "count": 0})
    )

    all_utilizations = []
    gpu_count = 0

    for record in records:
        ts = _parse_timestamp(record.get("timestamp", ""))
        if ts is None:
            continue
        if ts < start_time or ts > end_time:
            continue

        idx = _overlay_bucket_index(ts, scale)

        gpus = record.get("gpus", [])
        if gpus:
            gpu_count = max(gpu_count, len(gpus))

        for gpu in gpus:
            gpu_util = gpu.get("utilization_gpu", 0)
            all_utilizations.append(gpu_util)

            processes = gpu.get("processes", [])
            if processes:
                gpu_user_memory: Dict[str, float] = defaultdict(float)
                for proc in processes:
                    user = proc.get("user", "unknown")
                    mem = proc.get("used_memory_mb", 0)
                    gpu_user_memory[user] += mem

                for user, mem in gpu_user_memory.items():
                    # memory: SUM (overlay shows cumulative consumption)
                    user_bucket_data[user][idx]["memory_sum"] += mem
                    # utilization: sum now, divided by count -> AVG later
                    user_bucket_data[user][idx]["util_sum"] += gpu_util
                    user_bucket_data[user][idx]["count"] += 1

    # build the output
    timeline_labels = [label_fn(i) for i in range(bucket_count)]
    users_data, final_user_memory = _build_user_series(
        user_bucket_data, bucket_count, mode="overlay"
    )

    return _build_result(
        scale, "overlay", timeline_labels, users_data, final_user_memory,
        all_utilizations, gpu_count,
    )


# ── result helpers ─────────────────────────────────────────────────

def _empty_result(scale: str, mode: str = "linear") -> Dict[str, Any]:
    """Return the empty data structure."""
    return {
        "scale": scale,
        "mode": mode,
        "data": {
            "timeline": [],
            "users": {},
            "current_distribution": {},
            "overview": {"gpu_count": 0, "active_users": 0, "avg_utilization": 0},
        },
    }


def _build_user_series(
    user_bucket_data: Dict[str, Dict[int, Dict[str, float]]],
    bucket_count: int,
    mode: str,
) -> tuple:
    """Build per-user time series.

    Args:
        user_bucket_data: user -> bucket_idx -> {memory_sum, util_sum, count}
        bucket_count: number of buckets
        mode: "linear" | "overlay"

    Returns:
        (users_data: dict, final_user_memory: dict)

    - memory: AVG per bucket in linear mode, SUM in overlay mode
    - utilization: always AVG per bucket
    """
    users_data = {}
    all_users = sorted(user_bucket_data.keys())
    final_user_memory: Dict[str, float] = defaultdict(float)

    for user in all_users:
        memory_series = []
        util_series = []
        for i in range(bucket_count):
            bucket = user_bucket_data[user].get(i)
            if bucket and bucket["count"] > 0:
                if mode == "overlay":
                    # overlay: memory SUM
                    avg_mem = round(bucket["memory_sum"], 1)
                else:
                    # linear: memory AVG
                    avg_mem = round(bucket["memory_sum"] / bucket["count"], 1)
                avg_util = round(bucket["util_sum"] / bucket["count"], 1)
                memory_series.append(avg_mem)
                util_series.append(avg_util)
            else:
                memory_series.append(0)
                util_series.append(0)

        # per-user average memory across buckets (for the distribution)
        if memory_series:
            positive_vals = [v for v in memory_series if v > 0]
            final_user_memory[user] = round(
                sum(positive_vals) / len(positive_vals), 1
            ) if positive_vals else 0

        users_data[user] = {
            "gpu_memory_mb": memory_series,
            "gpu_util_pct": util_series,
        }

    return users_data, final_user_memory


def _build_result(
    scale: str,
    mode: str,
    timeline: list,
    users_data: dict,
    final_user_memory: dict,
    all_utilizations: list,
    gpu_count: int,
) -> Dict[str, Any]:
    """Build the final output structure."""
    # current_distribution
    total_memory = sum(final_user_memory.values())
    if total_memory > 0:
        current_distribution = {
            user: round(mem / total_memory * 100, 1)
            for user, mem in final_user_memory.items()
        }
    else:
        current_distribution = {}

    # number of users with any positive memory bucket
    active_users = len([u for u in users_data if any(
        v > 0 for v in users_data[u]["gpu_memory_mb"]
    )])

    # average GPU utilization
    avg_utilization = round(sum(all_utilizations) / len(all_utilizations), 1) if all_utilizations else 0

    return {
        "scale": scale,
        "mode": mode,
        "data": {
            "timeline": timeline,
            "users": users_data,
            "current_distribution": current_distribution,
            "overview": {
                "gpu_count": gpu_count,
                "active_users": active_users,
                "avg_utilization": avg_utilization,
            },
        },
    }


# ── main entry ─────────────────────────────────────────────────────

def aggregate_gpu_data(
    scale: str = "day",
    mode: str = "linear",
    start: Optional[Union[str, datetime]] = None,
    end: Optional[Union[str, datetime]] = None,
    lang: str = "en",
) -> Dict[str, Any]:
    """Aggregate GPU usage data for a time scale and display mode.

    Args:
        scale: time scale — "day" / "week" / "month" / "year"
        mode: display mode — "linear" (time-ordered) / "overlay"
              (aligned by position within the period)
        start: start date. Optional in linear mode (defaults to the
               scale window); required in overlay mode. Formats: ISO
               date ("2026-07-25"), ISO week ("2026-W30"), ISO month
               ("2026-07"), plain year ("2026").
        end:   end date, same formats as start.

    Returns:
        {
            "scale": str,
            "mode": str,
            "data": {
                "timeline": [...],
                "users": { "user": {"gpu_memory_mb": [...], "gpu_util_pct": [...]} },
                "current_distribution": { "user": percent },
                "overview": { "gpu_count", "active_users", "avg_utilization" },
            }
        }
    """
    # validate parameters
    if scale not in VALID_SCALES:
        scale = "day"
    if mode not in VALID_MODES:
        mode = "linear"

    # parse the date parameters
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None

    if start is not None:
        if isinstance(start, str):
            start_dt = _parse_date_param(start, scale)
        else:
            start_dt = start

    if end is not None:
        if isinstance(end, str):
            end_dt = _parse_date_param(end, scale)
        else:
            end_dt = end
        # end defaults to the last moment of its day/week/month/year
        if scale == "day":
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        elif scale == "week":
            end_dt = end_dt + timedelta(days=6)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        elif scale == "month":
            # last day of the month
            if end_dt.month == 12:
                end_dt = end_dt.replace(year=end_dt.year + 1, month=1, day=1)
            else:
                end_dt = end_dt.replace(month=end_dt.month + 1, day=1)
            end_dt = end_dt - timedelta(seconds=1)
        elif scale == "year":
            end_dt = end_dt.replace(month=12, day=31, hour=23, minute=59, second=59)

    # resolve the window and read the data
    if mode == "overlay":
        if start_dt is None or end_dt is None:
            return _empty_result(scale, mode)
        records = read_gpu_history(start_time=start_dt, end_time=end_dt)
        return _aggregate_overlay(records, scale, start_dt, end_dt, lang)

    # linear mode
    linear_start, linear_end, _ = _get_scale_bounds(
        scale, start_time=start_dt, end_time=end_dt
    )
    records = read_gpu_history(start_time=linear_start, end_time=linear_end)
    if not records:
        return _empty_result(scale, "linear")
    return _aggregate_linear(records, scale, linear_start, linear_end)
