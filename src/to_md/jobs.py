"""In-memory Job store: a Conversion in flight or recently finished.

Finished Jobs are swept after a retention window rather than kept forever,
so the store never grows without bound and a container restart is the only
way to lose state (accepted trade-off — see ADR-0001).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from threading import Lock


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.QUEUED
    markdown: str | None = None
    html: str | None = None
    filename: str | None = None
    error: str | None = None
    finished_at: float | None = None


class JobStore:
    def __init__(self, retention_seconds: float) -> None:
        self._retention_seconds = retention_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
        return replace(job)

    def get(self, job_id: str) -> Job | None:
        """Returns a snapshot, safe to read without racing an in-flight update."""
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else replace(job)

    def _update(self, job_id: str, apply: Callable[[Job], None]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                apply(job)

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, lambda job: setattr(job, "status", JobStatus.RUNNING))

    def mark_done(self, job_id: str, markdown: str, html: str, filename: str) -> None:
        def apply(job: Job) -> None:
            job.status = JobStatus.DONE
            job.markdown = markdown
            job.html = html
            job.filename = filename
            job.finished_at = time.monotonic()

        self._update(job_id, apply)

    def mark_error(self, job_id: str, message: str) -> None:
        def apply(job: Job) -> None:
            job.status = JobStatus.ERROR
            job.error = message
            job.finished_at = time.monotonic()

        self._update(job_id, apply)

    def sweep(self) -> None:
        """Remove finished Jobs whose retention window has elapsed."""
        now = time.monotonic()
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.finished_at is not None
                and now - job.finished_at >= self._retention_seconds
            ]
            for job_id in expired:
                del self._jobs[job_id]
