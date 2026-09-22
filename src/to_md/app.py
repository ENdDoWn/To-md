"""The web application: serves the page and the Job endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .convert import convert_to_markdown
from .jobs import JobStore

logger = logging.getLogger("to_md")

STATIC_DIR = Path(__file__).parent / "static"

# Accepted Source extensions. The walking skeleton handles DOCX only;
# later issues widen this allowlist.
ACCEPTED_EXTENSIONS = {".docx"}

WORKER_COUNT = int(os.environ.get("TO_MD_WORKERS", "2"))
RETENTION_SECONDS = float(os.environ.get("TO_MD_RETENTION_SECONDS", "600"))
SWEEP_INTERVAL_SECONDS = 30

job_store = JobStore(retention_seconds=RETENTION_SECONDS)
executor = ThreadPoolExecutor(max_workers=WORKER_COUNT)


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        job_store.sweep()


@asynccontextmanager
async def lifespan(app: FastAPI):
    sweep_task = asyncio.create_task(_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(lifespan=lifespan)


def _run_conversion(job_id: str, source: bytes, extension: str, filename: str) -> None:
    job_store.mark_running(job_id)
    try:
        markdown = convert_to_markdown(source, extension)
    except Exception:  # noqa: BLE001 - conversion failures become a clean Job error
        logger.exception("conversion failed for job %s", job_id)
        job_store.mark_error(job_id, "conversion failed")
        return
    job_store.mark_done(job_id, markdown, _suggested_filename(filename))


def _log_unhandled(future: asyncio.Future) -> None:
    """Surfaces exceptions that escape `_run_conversion` itself, so a bug in the
    Job-store bookkeeping doesn't leave a Job silently stuck at `running`."""
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        logger.error("job worker raised unexpectedly", exc_info=exc)


def _suggested_filename(source_filename: str) -> str:
    stem = Path(source_filename).stem or "converted"
    return f"{stem}.md"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile) -> JSONResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ACCEPTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported file type")

    source = await file.read()
    job = job_store.create()

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        executor, _run_conversion, job.id, source, extension, file.filename or "source"
    )
    future.add_done_callback(_log_unhandled)

    return JSONResponse({"id": job.id}, status_code=202)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=404, detail="not found")

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")

    body = {"status": job.status.value}
    if job.status.value == "done":
        body["markdown"] = job.markdown
        body["filename"] = job.filename
    elif job.status.value == "error":
        body["error"] = job.error

    return JSONResponse(body)
