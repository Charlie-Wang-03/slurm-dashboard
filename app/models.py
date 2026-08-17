from dataclasses import dataclass


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    job_name: str
    script_name: str
    source: str          # "paste" | "upload" | "external"
    submit_time: str
    partition: str
    gres: str
    cpus_per_task: int
    mem: str
    time_limit: str
    status: str = "SUBMITTED"
    workspace_path: str = ""
    output_path: str = ""  # path of slurm-<jobid>.out
