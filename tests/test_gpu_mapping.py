"""GPU process -> GPU attribution by PCI bus id (no GPU-0 fallback).

Regression tests for the multi-GPU mapping in tools/gpu_monitor.py:
processes must be attached to the GPU they actually run on (identified
by PCI bus id), and processes whose GPU cannot be determined must never
be defaulted to GPU 0.
"""

from tools.gpu_monitor import (
    _bus_ids_match,
    _normalize_bus_id,
    attach_processes_to_gpus,
    get_gpu_info,
)


def _gpu(index, bus_id):
    return {"index": index, "bus_id": bus_id, "processes": []}


def _proc(pid, gpu_bus_id=""):
    return {"pid": pid, "gpu_bus_id": gpu_bus_id, "user": "u", "used_memory_mb": 100.0}


class TestNormalizeBusId:
    def test_lowercases_and_strips(self):
        assert _normalize_bus_id("  00000000:3D:00.0  ") == "00000000:3d:00.0"

    def test_empty_stays_empty(self):
        assert _normalize_bus_id("") == ""
        assert _normalize_bus_id(None) == ""


class TestBusIdsMatch:
    def test_exact_match(self):
        assert _bus_ids_match("00000000:3D:00.0", "00000000:3d:00.0")

    def test_full_vs_short_form(self):
        assert _bus_ids_match("00000000:3D:00.0", "3D:00.0")

    def test_no_match_between_different_buses(self):
        assert not _bus_ids_match("00000000:3D:00.0", "00000000:4D:00.0")

    def test_empty_never_matches(self):
        assert not _bus_ids_match("", "00000000:3D:00.0")
        assert not _bus_ids_match("3D:00.0", "")


class TestAttachProcessesToGpus:
    def test_multi_gpu_processes_land_on_their_own_gpu(self):
        """Processes on GPU 1 and GPU 2 must not be dumped onto GPU 0."""
        gpus = [
            _gpu(0, "00000000:01:00.0"),
            _gpu(1, "00000000:02:00.0"),
            _gpu(2, "00000000:03:00.0"),
        ]
        processes = [
            _proc(100, "00000000:01:00.0"),
            _proc(200, "00000000:02:00.0"),
            _proc(300, "00000000:03:00.0"),
        ]
        gpus, unmatched = attach_processes_to_gpus(gpus, processes)
        assert unmatched == []
        assert [p["pid"] for p in gpus[0]["processes"]] == [100]
        assert [p["pid"] for p in gpus[1]["processes"]] == [200]
        assert [p["pid"] for p in gpus[2]["processes"]] == [300]

    def test_short_form_bus_id_still_matches(self):
        """nvidia-smi may report compute-apps bus ids in short form."""
        gpus = [
            _gpu(0, "00000000:01:00.0"),
            _gpu(1, "00000000:02:00.0"),
        ]
        processes = [_proc(200, "02:00.0")]  # short form of GPU 1
        gpus, unmatched = attach_processes_to_gpus(gpus, processes)
        assert unmatched == []
        assert gpus[0]["processes"] == []
        assert [p["pid"] for p in gpus[1]["processes"]] == [200]

    def test_unmatched_process_never_falls_back_to_gpu_0(self):
        """An unmatchable process must not be attributed to any GPU."""
        gpus = [_gpu(0, "00000000:01:00.0")]
        processes = [_proc(900, "00000000:99:00.0")]  # vanished / unknown GPU
        gpus, unmatched = attach_processes_to_gpus(gpus, processes)
        assert gpus[0]["processes"] == []
        assert len(unmatched) == 1
        assert unmatched[0]["pid"] == 900

    def test_missing_bus_ids_never_fabricate_attribution(self):
        """Neither side exposing a bus id -> every process unmatched."""
        gpus = [_gpu(0, "")]
        processes = [_proc(900, "")]
        gpus, unmatched = attach_processes_to_gpus(gpus, processes)
        assert gpus[0]["processes"] == []
        assert len(unmatched) == 1

    def test_single_gpu_still_attaches(self):
        """The common single-GPU case keeps working."""
        gpus = [_gpu(0, "00000000:01:00.0")]
        processes = [_proc(100, "00000000:01:00.0"), _proc(101, "01:00.0")]
        gpus, unmatched = attach_processes_to_gpus(gpus, processes)
        assert unmatched == []
        assert sorted(p["pid"] for p in gpus[0]["processes"]) == [100, 101]

    def test_input_dicts_are_mutated_in_place(self):
        """Attaching appends the original process dicts to the GPU."""
        gpus = [_gpu(0, "00000000:01:00.0")]
        proc = _proc(100, "00000000:01:00.0")
        attach_processes_to_gpus(gpus, [proc])
        assert gpus[0]["processes"][0] is proc


class TestGpuQueryFields:
    """The --query-gpu field list must be valid on real nvidia-smi.

    Regression: v0.1.1 used the bare ``bus_id`` field, which real
    nvidia-smi rejects ("Field 'bus_id' is not a valid field to query").
    These tests capture the actually constructed command instead of
    feeding mock data to the parser, so a field-name typo can never be
    hidden by mocked nvidia-smi output.
    """

    def test_query_gpu_uses_valid_pci_bus_id_field(self, monkeypatch):
        captured = {}

        class FakeResult:
            returncode = 0
            stdout = (
                "0, NVIDIA GeForce RTX 4090, 0, 0, 3, 24564, 25, "
                "00000000:17:00.0\n"
            )
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return FakeResult()

        monkeypatch.setattr("tools.gpu_monitor.subprocess.run", fake_run)
        gpus = get_gpu_info()

        query = captured["cmd"][1]
        fields = query.split("=", 1)[1].split(",")
        assert fields == [
            "index",
            "name",
            "utilization.gpu",
            "utilization.memory",
            "memory.used",
            "memory.total",
            "temperature.gpu",
            "pci.bus_id",
        ]
        # the invalid bare field must never appear
        assert "bus_id" not in fields
        # and the parsed GPU carries the real bus id
        assert len(gpus) == 1
        assert gpus[0]["bus_id"] == "00000000:17:00.0"
