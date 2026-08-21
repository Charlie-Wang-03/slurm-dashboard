"""GPU history aggregation: overlay bucket labels follow the UI language,
and timestamps parse as timezone-aware ISO 8601 (legacy +08:00 included).
"""

from datetime import timedelta

from app.gpu_history import _get_overlay_buckets, _parse_timestamp


class TestOverlayBucketLabels:
    def test_day_labels_are_time_of_day(self):
        count, label_fn = _get_overlay_buckets("day", lang="en")
        assert count == 288
        assert label_fn(0) == "00:00"
        assert label_fn(12) == "01:00"
        assert label_fn(287) == "23:55"

    def test_week_labels_zh(self):
        _, label_fn = _get_overlay_buckets("week", lang="zh")
        assert [label_fn(i) for i in range(7)] == [
            "周一", "周二", "周三", "周四", "周五", "周六", "周日",
        ]

    def test_week_labels_en(self):
        _, label_fn = _get_overlay_buckets("week", lang="en")
        assert [label_fn(i) for i in range(7)] == [
            "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
        ]

    def test_month_labels(self):
        _, zh_fn = _get_overlay_buckets("month", lang="zh")
        _, en_fn = _get_overlay_buckets("month", lang="en")
        assert zh_fn(0) == "1日"
        assert zh_fn(30) == "31日"
        assert en_fn(0) == "1"
        assert en_fn(30) == "31"

    def test_year_labels(self):
        _, zh_fn = _get_overlay_buckets("year", lang="zh")
        _, en_fn = _get_overlay_buckets("year", lang="en")
        assert zh_fn(0) == "第1周"
        assert zh_fn(51) == "第52周"
        assert en_fn(0) == "W1"
        assert en_fn(51) == "W52"

    def test_aggregate_overlay_full_path(self):
        """End-to-end: aggregate_gpu_data must thread lang into overlay labels."""
        from app.gpu_history import aggregate_gpu_data

        zh = aggregate_gpu_data(
            scale="week", mode="overlay",
            start="2026-W33", end="2026-W33", lang="zh",
        )
        en = aggregate_gpu_data(
            scale="week", mode="overlay",
            start="2026-W33", end="2026-W33", lang="en",
        )
        zh_labels = zh["data"]["timeline"]
        en_labels = en["data"]["timeline"]
        assert zh_labels[0] == "周一"
        assert en_labels[0] == "Mon"
        assert zh_labels != en_labels


class TestTimestampParsing:
    """Timezone-aware ISO 8601 parsing; legacy v0.1.0 +08:00 data."""

    def test_legacy_plus_0800_parsed_aware(self):
        dt = _parse_timestamp("2026-07-10T09:59:02+08:00")
        assert dt is not None
        assert dt.utcoffset() == timedelta(hours=8)
        assert dt.hour == 9

    def test_arbitrary_offsets_parsed(self):
        dt = _parse_timestamp("2026-07-10T12:00:00+05:30")
        assert dt is not None
        assert dt.utcoffset() == timedelta(hours=5, minutes=30)
        dt2 = _parse_timestamp("2026-07-10T12:00:00-07:00")
        assert dt2 is not None
        assert dt2.utcoffset() == -timedelta(hours=7)

    def test_naive_timestamp_gets_local_tz(self):
        dt = _parse_timestamp("2026-07-10T09:59:02")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_new_collector_format_with_microseconds(self):
        dt = _parse_timestamp("2026-08-20T21:30:00.123456+08:00")
        assert dt is not None
        assert dt.utcoffset() == timedelta(hours=8)

    def test_same_instant_across_offsets_compares_equal(self):
        beijing = _parse_timestamp("2026-07-10T09:59:02+08:00")
        utc = _parse_timestamp("2026-07-10T01:59:02+00:00")
        assert beijing == utc  # aware datetimes compare by instant

    def test_garbage_returns_none(self):
        assert _parse_timestamp("not-a-date") is None
        assert _parse_timestamp("") is None
        assert _parse_timestamp(None) is None


class TestAggregationWithLegacyData:
    """aggregate_gpu_data must keep reading v0.1.0 (+08:00) history files."""

    LEGACY_LINE = (
        '{"timestamp": "2026-07-10T09:59:02+08:00", "gpus": ['
        '{"index": 0, "utilization_gpu": 50.0, "processes": ['
        '{"user": "alice", "used_memory_mb": 1024.0}]}]}'
    )

    def _write_history(self, tmp_path, lines):
        hist = tmp_path / "gpu_history.jsonl"
        hist.write_text("\n".join(lines) + "\n", encoding="utf-8")
        import app.gpu_history as gh
        gh.HISTORY_FILE = hist

    def test_legacy_plus_0800_records_aggregate(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gpu_history.HISTORY_FILE", tmp_path / "h.jsonl")
        (tmp_path / "h.jsonl").write_text(self.LEGACY_LINE + "\n", encoding="utf-8")
        from app.gpu_history import aggregate_gpu_data

        data = aggregate_gpu_data(scale="day", mode="linear",
                                  start="2026-07-10", end="2026-07-10")
        alice_memory = data["data"]["users"]["alice"]["gpu_memory_mb"]
        assert any(v > 0 for v in alice_memory)

    def test_mixed_offsets_same_instant_land_in_same_bucket(self, tmp_path, monkeypatch):
        """A +08:00 record and a UTC record at the same instant both count."""
        import app.gpu_history as gh
        monkeypatch.setattr("app.gpu_history.HISTORY_FILE", tmp_path / "h.jsonl")
        lines = [
            self.LEGACY_LINE,  # 09:59:02+08:00 == 01:59:02Z
            '{"timestamp": "2026-07-10T01:59:02+00:00", "gpus": ['
            '{"index": 0, "utilization_gpu": 50.0, "processes": ['
            '{"user": "bob", "used_memory_mb": 512.0}]}]}',
        ]
        (tmp_path / "h.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        from app.gpu_history import aggregate_gpu_data

        data = aggregate_gpu_data(scale="day", mode="linear",
                                  start="2026-07-10", end="2026-07-10")
        assert any(v > 0 for v in data["data"]["users"]["alice"]["gpu_memory_mb"])
        assert any(v > 0 for v in data["data"]["users"]["bob"]["gpu_memory_mb"])
