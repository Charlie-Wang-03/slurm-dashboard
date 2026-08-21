"""Whitelist validation tests for app/slurm.py (v2 submit model).

The whitelists are monkeypatched so the tests pass on a fresh clone
without any config.local.json (they must not depend on the author's
machine configuration).
"""

import pytest

from app.slurm import (
    validate_cpus_per_task,
    validate_gres,
    validate_job_name,
    validate_mem,
    validate_partition,
    validate_script_filename,
    validate_slurm_job_id,
    validate_time_limit,
)


@pytest.fixture()
def whitelist(monkeypatch):
    """A concrete partition/GRES allowlist for the whitelist tests."""
    import app.slurm as slurm

    monkeypatch.setattr(slurm, "ALLOWED_PARTITIONS", ["GPU", "CPU"])
    monkeypatch.setattr(slurm, "ALLOWED_GRES", ["gpu:1", "gpu:2"])


class TestJobName:
    def test_valid_names(self):
        assert validate_job_name("hello") == "hello"
        assert validate_job_name("train_v2-3") == "train_v2-3"

    def test_rejects_invalid(self):
        for bad in ["", "has space", "a/b", "a.b", "汉字"]:
            with pytest.raises(ValueError):
                validate_job_name(bad)


class TestPartitionWhitelist:
    def test_allowed_partition_passes(self, whitelist):
        assert validate_partition("GPU") == "GPU"
        assert validate_partition("CPU") == "CPU"

    def test_disallowed_partition_rejected(self, whitelist):
        with pytest.raises(ValueError):
            validate_partition("highprio")

    def test_empty_partition_is_slurm_default(self, whitelist):
        """Empty = no --partition flag (SLURM's native default)."""
        assert validate_partition("") == ""
        assert validate_partition(None) == ""


class TestGresWhitelist:
    def test_allowed_gres_passes(self, whitelist):
        assert validate_gres("gpu:1") == "gpu:1"
        assert validate_gres("gpu:2") == "gpu:2"

    def test_disallowed_gres_rejected(self, whitelist):
        with pytest.raises(ValueError):
            validate_gres("gpu:8")

    def test_empty_gres_is_slurm_default(self, whitelist):
        """Empty = no --gres flag (SLURM's native default)."""
        assert validate_gres("") == ""
        assert validate_gres(None) == ""


class TestCpus:
    def test_valid_range(self):
        assert validate_cpus_per_task(1) == 1
        assert validate_cpus_per_task(32) == 32

    def test_rejects_out_of_range(self):
        for bad in [0, 33, -1]:
            with pytest.raises(ValueError):
                validate_cpus_per_task(bad)

    def test_rejects_non_integer(self):
        with pytest.raises(ValueError):
            validate_cpus_per_task("many")


class TestMem:
    def test_valid(self):
        assert validate_mem("16G") == "16G"
        assert validate_mem("64000M") == "64000M"

    def test_rejects_invalid(self):
        for bad in ["16", "16GB", "", "0G"]:
            with pytest.raises(ValueError):
                validate_mem(bad)


class TestTimeLimit:
    def test_valid(self):
        assert validate_time_limit("00:30:00") == "00:30:00"
        assert validate_time_limit("1-00:00:00") == "1-00:00:00"

    def test_rejects_invalid(self):
        for bad in ["30:00", "00:60:00", "", "2h"]:
            with pytest.raises(ValueError):
                validate_time_limit(bad)


class TestScriptFilename:
    def test_valid(self):
        assert validate_script_filename("run.sbatch") == "run.sbatch"
        assert validate_script_filename("my_script.sh") == "my_script.sh"
        assert validate_script_filename("train.py") == "train.py"

    def test_rejects_invalid(self):
        for bad in ["", "noext", "a/b.sh", "../evil.sh", "a\\b.sh", "train.py.exe"]:
            with pytest.raises(ValueError):
                validate_script_filename(bad)


class TestJobId:
    def test_valid(self):
        assert validate_slurm_job_id("12345") == "12345"

    def test_rejects_invalid(self):
        for bad in ["", "abc", "12a", None]:
            with pytest.raises(ValueError):
                validate_slurm_job_id(bad)
