"""HTTP API.

Start with:  python run.py serve
Interactive documentation is served at /docs by FastAPI.
"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .assistant import LegalAssistant

app = FastAPI(
    title="Multi Jurisdictional Traffic Light Incident Legal Assistant",
    version=__version__,
    description=("Hybrid structured and unstructured RAG that evaluates clearance interval compliance at the "
                 "millisecond of stop line entry and cites federal, state, local and hardware authority."),
)


class Question(BaseModel):
    question: str
    save_report: bool = False


class SqlRequest(BaseModel):
    sql: str
    limit: int = 200


@lru_cache(maxsize=1)
def assistant():
    return LegalAssistant()


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/crashes")
def crashes(limit: int = 50, intersection_id: str = ""):
    return assistant().db.crashes(limit, intersection_id or None)


@app.get("/crashes/{crash_id}/evaluation")
def evaluate(crash_id: str, evidence: bool = True):
    try:
        return assistant().evaluator.evaluate(crash_id.upper(), with_evidence=evidence)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/crashes/{crash_id}/memo")
def memo_markdown(crash_id: str):
    try:
        return {"markdown": assistant().crash_report(crash_id.upper(), save_report=False)["answer_markdown"]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/ask")
def ask(body: Question):
    try:
        return assistant().ask(body.question, save_report=body.save_report)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/retrieve")
def retrieve(q: str, state_code: str = "", jurisdiction_code: str = "", k: int = 8):
    results = assistant().rag.retrieve(q, state_code=state_code or None, jurisdiction_code=jurisdiction_code or None, k=k)
    return [r.as_dict() for r in results]


@app.post("/sql")
def sql(body: SqlRequest):
    try:
        return assistant().db.query(body.sql, limit=min(body.limit, 1000))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
