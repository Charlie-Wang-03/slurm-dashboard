"""Python-script submission: automatic sbatch wrapper generation.

Covers build_python_wrapper() and submit_script()'s .py branch, with
subprocess.run mocked so no real job is submitted.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.slurm import build_python_wrapper, submit_script


def test_build_python_wrapper_structure():
    wrapper = build_python_wrapper(
        script_relpath="scripts/train.py",
        job_name="hello",
        partition="GPU",
        gres="gpu:1",
        cpus_per_task=4,
        mem="16G",
        time_limit="00:30:00",
        workspace=Path("/tmp/ws"),
    )
    assert wrapper.startswith("#!/usr/bin/env bash\n")
    assert "#SBATCH --job-name=hello" in wrapper
    assert "#SBATCH --partition=GPU" in wrapper
    assert "#SBATCH --gres=gpu:1" in wrapper
    assert "#SBATCH --cpus-per-task=4" in wrapper
    assert "#SBATCH --mem=16G" in wrapper
    assert "#SBATCH --time=00:30:00" in wrapper
    assert "set -euo pipefail" in wrapper
    assert "cd /tmp/ws" in wrapper
    assert "python3 scripts/train.py" in wrapper


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_submit_script_python_writes_source_and_wrapper(tmp_path, monkeypatch):
    """A .py script is stored next to an auto-generated run_*.sbatch wrapper,
    and the wrapper (not the source) is what gets submitted."""
    monkeypatch.setattr(
        "app.slurm.subprocess.run",
        lambda *a, **k: FakeCompleted(stdout="Submitted batch job 424242\n"),
    )
    monkeypatch.setattr("app.slurm.SETTINGS", type("S", (), {
        "allowed_partitions": ["GPU"],
        "allowed_gres": ["gpu:1"],
        "slurm_partition": "GPU",
        "default_gres": "gpu:1",
        "default_cpus": 4,
        "default_mem": "16G",
        "default_time": "00:30:00",
    })())
    monkeypatch.setattr("app.slurm.ALLOWED_PARTITIONS", ["GPU"])
    monkeypatch.setattr("app.slurm.ALLOWED_GRES", ["gpu:1"])

    result = submit_script(
        script_content="print('hello')",
        script_filename="train.py",
        job_name="hello",
        partition="GPU",
        gres="gpu:1",
        cpus_per_task=4,
        mem="16G",
        time_limit="00:30:00",
        workspace=tmp_path,
        source="paste",
    )

    scripts = sorted(p.name for p in (tmp_path / "scripts").iterdir())
    assert any(name == "train.py" or name.startswith("train_") for name in scripts)
    assert any(name.startswith("run_train_") and name.endswith(".sbatch") for name in scripts)
    assert result.job_id == "424242"

    wrapper_path = next(p for p in (tmp_path / "scripts").iterdir() if p.name.startswith("run_train_"))
    wrapper_content = wrapper_path.read_text(encoding="utf-8")
    assert "#SBATCH --partition=GPU" in wrapper_content
    assert wrapper_path.name.endswith(".sbatch")


def test_submit_script_python_invalid_name_rejected(tmp_path):
    with pytest.raises(ValueError, match=r"\.sh, \.sbatch or \.py"):
        submit_script(
            script_content="x",
            script_filename="train.py.exe",
            job_name="hello",
            partition="GPU",
            gres="gpu:1",
            cpus_per_task=4,
            mem="16G",
            time_limit="00:30:00",
            workspace=tmp_path,
            source="paste",
        )
