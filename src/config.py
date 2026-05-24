"""
Configuracao de variaveis de ambiente e constantes da aplicacao.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
OPENROUTER_TEMPERATURE = float(os.getenv("OPENROUTER_TEMPERATURE", "0.0"))

# Node.js Backend
NODE_BACKEND_URL = os.getenv("NODE_BACKEND_URL", "http://localhost:3000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "cade-internal-key-2026")

# ChromaDB
CHROMA_PERSIST_PATH = os.getenv("CHROMA_PERSIST_PATH", "./chroma_db")

# Debug
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
