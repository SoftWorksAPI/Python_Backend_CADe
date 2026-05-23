import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from src.api import router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

app = FastAPI(
    title="CADe Content API",
    version="2.0.0",
    description="API para extracao de dados DXF, geracao de Memorial Descritivo com IA e RAG de normas tecnicas.",
)

app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
