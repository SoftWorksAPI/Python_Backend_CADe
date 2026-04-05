# Python Backend CADe

API em FastAPI para extrair informacoes de arquivos DXF e retornar os dados em JSON.

## Visao geral

O projeto recebe um arquivo `.dxf` via `multipart/form-data`, processa as entidades CAD e retorna:
- resumo por `layer` e tipo
- elementos geometricos (linhas, polylines e areas)
- blocos inseridos no desenho
- textos (`TEXT` e `MTEXT`)
- ambientes detectados por polygonizacao

A documentacao interativa fica disponivel em `/docs`.

## Stack

- Python
- FastAPI
- Pydantic
- ezdxf
- Shapely
- Uvicorn

## Estrutura do projeto

```text
src/
  main.py
  api/
    v1/
      routes/
      schemas/
      services/
  core/
```

## Requisitos

- Python `>=3.14`
- `uv` (recomendado) ou `pip`

## Instalacao

### Opcao 1: com uv (recomendado)

```bash
uv sync
```

### Opcao 2: com pip

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
pip install -e .
```

## Executando a aplicacao

### Com uv

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

### Com python/uvicorn

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

Acesse:
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`

## Endpoint principal

### `POST /v1/extract/dxf`

Extrai informacoes de um arquivo DXF.

#### Payload (`multipart/form-data`)

- `file` (obrigatorio): arquivo com extensao `.dxf`
- `min_environment_area` (opcional, default `1.0`): area minima para considerar um ambiente
- `include_elements` (opcional, default `true`)
- `include_blocks` (opcional, default `true`)
- `include_texts` (opcional, default `true`)
- `include_environments` (opcional, default `true`)

#### Exemplo com curl

```bash
curl -X POST "http://localhost:8080/v1/extract/dxf" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@Base.dxf;type=application/octet-stream" \
  -F "min_environment_area=2.5" \
  -F "include_elements=true" \
  -F "include_blocks=true" \
  -F "include_texts=true" \
  -F "include_environments=true"
```

#### Exemplo resumido de resposta

```json
{
  "arquivo": "Base.dxf",
  "total_entidades": 142,
  "resumo": [
    {
      "layer": "ARQ_PAREDES",
      "tipo": "LINE",
      "quantidade": 34,
      "total_comprimento": 218.54,
      "total_area": 0.0
    }
  ],
  "elementos": [],
  "blocos": [],
  "textos": [],
  "ambientes": []
}
```

## Codigos de resposta esperados

- `200`: extracao concluida com sucesso
- `400`: arquivo invalido, vazio, ou sem extensao `.dxf`
- `422`: nao foi possivel processar o DXF

## Arquivos de apoio

- `Base.dxf`: exemplo de arquivo DXF para testes locais

## Observacoes

- O endpoint raiz (`/`) redireciona para `/docs`.
- CORS esta liberado para todas as origens (`*`) no estado atual.
