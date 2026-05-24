"""
Rotas para download de relatorios gerados.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

OUTPUT_DIR = Path(__file__).parent.parent / "services" / "report" / "output"

router = APIRouter()


@router.get(
    "/reports/list",
    summary="Lista relatorios gerados",
)
async def list_reports():
    if not OUTPUT_DIR.exists():
        return {"relatorios": []}

    arquivos = []
    for f in sorted(OUTPUT_DIR.iterdir()):
        if f.is_file() and f.suffix in (".md", ".pdf", ".xlsx"):
            arquivos.append({
                "nome": f.name,
                "tipo": f.suffix.lstrip("."),
                "tamanho_kb": round(f.stat().st_size / 1024, 1),
            })

    return {"relatorios": arquivos}


@router.get(
    "/reports/download/{filename}",
    summary="Download de um relatorio gerado",
)
async def download_report(filename: str):
    caminho = OUTPUT_DIR / filename

    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    # Determinar media type
    ext = caminho.suffix.lower()
    media_types = {
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    return FileResponse(
        path=str(caminho),
        filename=filename,
        media_type=media_types.get(ext, "application/octet-stream"),
    )
