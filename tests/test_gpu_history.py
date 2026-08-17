"""GPU history aggregation: overlay bucket labels follow the UI language."""

from app.gpu_history import _get_overlay_buckets


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
        from datetime import datetime

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
