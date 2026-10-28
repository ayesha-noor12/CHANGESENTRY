"""FastAPI coordinator for ChangeSentry."""
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import allowed_origins, nebius_configured, tavily_configured
from app.models import AnalysisRun, AnalyzeRequest
from app.nemotron_client import model_name
from app.pipeline import STORE, run_analysis
from app.scenarios import get_scenario, list_scenarios

app = FastAPI(title="ChangeSentry API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health():
    """Reports which integrations are configured - never their values."""
    return {
        "status": "ok",
        "nemotron_configured": nebius_configured(),
        "model": model_name() if nebius_configured() else None,
        "tavily_configured": tavily_configured(),
    }


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": [s.summary.model_dump() for s in list_scenarios()]}


@app.post("/api/analyze", response_model=AnalysisRun)
def analyze(request: AnalyzeRequest):
    if get_scenario(request.scenario_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{request.scenario_id}'")
    run = STORE.create(request.scenario_id)
    if request.wait:
        run_analysis(run.run_id)
    else:
        threading.Thread(target=run_analysis, args=(run.run_id,), daemon=True).start()
    return STORE.get(run.run_id)


@app.get("/api/analysis/{run_id}", response_model=AnalysisRun)
def analysis(run_id: str):
    run = STORE.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run id")
    return run
