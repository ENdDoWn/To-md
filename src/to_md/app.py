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
from .render import render_to_html

logger = logging.getLogger("to_md")

STATIC_DIR = Path(__file__).parent / "static"

# The server-side allowlist: the real gate, regardless of what the client sent.
ACCEPTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
    ".epub",
    ".txt",
    ".md",
}
ACCEPTED_FORMATS_LABEL = ", ".join(sorted(ext.removeprefix(".") for ext in ACCEPTED_EXTENSIONS))

WORKER_COUNT = int(os.environ.get("TO_MD_WORKERS", "2"))
RETENTION_SECONDS = float(os.environ.get("TO_MD_RETENTION_SECONDS", "600"))
MAX_UPLOAD_BYTES = int(os.environ.get("TO_MD_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
POLL_INTERVAL_MS = int(os.environ.get("TO_MD_POLL_INTERVAL_MS", "1500"))
UPLOAD_CHUNK_BYTES = 1024 * 1024
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
        job_store.mark_error(job_id, "Could not convert this file — it may be corrupt.")
        return
    html = render_to_html(markdown)
    job_store.mark_done(job_id, markdown, html, _suggested_filename(filename))


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


def _max_upload_label() -> str:
    return f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB"


async def _read_within_limit(file: UploadFile, limit: int) -> bytes:
    """Reads the Source in bounded chunks, rejecting as soon as `limit` is
    exceeded rather than buffering an oversized upload into memory first."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"Source exceeds the {_max_upload_label()} limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/api/config")
async def config() -> JSONResponse:
    return JSONResponse({"pollIntervalMs": POLL_INTERVAL_MS})


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile) -> JSONResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ACCEPTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type; accepted formats: {ACCEPTED_FORMATS_LABEL}",
        )

    source = await _read_within_limit(file, MAX_UPLOAD_BYTES)
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
        body["html"] = job.html
        body["filename"] = job.filename
    elif job.status.value == "error":
        body["error"] = job.error

    return JSONResponse(body)
