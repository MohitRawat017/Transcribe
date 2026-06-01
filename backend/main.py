from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import blogger_auth
from backend.jobs import JobStore
from backend.orchestrator import ActiveJobError, PipelineOrchestrator

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

app = FastAPI(title="YouTube to Blogger Pipeline")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = JobStore(REPO_ROOT / "data" / "jobs.sqlite")
orchestrator = PipelineOrchestrator(REPO_ROOT, store)


class JobCreateRequest(BaseModel):
    channel_url: str
    start: int
    end: int


@app.get("/api/auth/blogger/status")
def blogger_status():
    return blogger_auth.get_status(REPO_ROOT)


@app.post("/api/auth/blogger/connect")
def blogger_connect():
    try:
        return blogger_auth.connect(REPO_ROOT)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: JobCreateRequest):
    channel_url = payload.channel_url.strip()
    if not channel_url:
        raise HTTPException(status_code=400, detail="channel_url is required.")
    if payload.start < 1:
        raise HTTPException(status_code=400, detail="start must be at least 1.")
    if payload.end < payload.start:
        raise HTTPException(status_code=400, detail="end must be greater than or equal to start.")

    auth = blogger_auth.get_status(REPO_ROOT)
    if not auth["ready"]:
        raise HTTPException(status_code=409, detail=auth["message"])

    try:
        return orchestrator.submit(channel_url, payload.start, payload.end)
    except ActiveJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.get("/api/health")
def health():
    return {"ok": True}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/")
    def frontend_missing():
        return JSONResponse(
            {
                "message": "Frontend build not found. Run npm install and npm run build in frontend/."
            }
        )
