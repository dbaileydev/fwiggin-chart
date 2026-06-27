from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .backtest_service import run_pine_backtest
from .date_ranges import DateRangeKey

app = FastAPI(title="MNQ Backtest API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BacktestRequest(BaseModel):
    pineScript: str = Field(min_length=1)
    range: DateRangeKey = "90d"
    symbol: str = "NQ=F"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/backtest")
def backtest(body: BacktestRequest) -> dict:
    try:
        return run_pine_backtest(
            body.pineScript,
            range_key=body.range,
            symbol=body.symbol,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/backtest/upload")
async def backtest_upload(
    file: UploadFile = File(...),
    range: DateRangeKey = Form("90d"),
    symbol: str = Form("NQ=F"),
) -> dict:
    try:
        raw = await file.read()
        pine_source = raw.decode("utf-8", errors="replace")
        return run_pine_backtest(pine_source, range_key=range, symbol=symbol)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
