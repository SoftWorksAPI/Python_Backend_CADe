"""
Configuracao de variaveis de ambiente e constantes da aplicacao.
"""
import os
from dotenv import load_dotenv

# Carregar variaveis do arquivo .env
load_dotenv()

# OpenRouter API
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
OPENROUTER_TEMPERATURE = float(os.getenv("OPENROUTER_TEMPERATURE", "0.0"))

# Configuracoes de aplicacao
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
