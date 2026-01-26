from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import json

app = FastAPI(title="Mock Bank Server", version="1.0.0")
DATA_DIR = Path("/data/bank_stub")

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/bank/transactions")
def get_transactions(user_id: str):
    file = DATA_DIR / f"transactions_{user_id}.json"
    if not file.exists():
        raise HTTPException(status_code=404, detail="user not found")
    return JSONResponse(content=json.loads(file.read_text()))
