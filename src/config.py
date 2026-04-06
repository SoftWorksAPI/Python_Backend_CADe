"""
Configuração de variáveis de ambiente e constantes da aplicação.
"""
import os
from dotenv import load_dotenv

# Carregar variáveis do arquivo .env
load_dotenv()

# Google Gemini API
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY não configurada. "
        "Copie .env.example para .env e adicione sua chave de API."
    )

# Configurações de aplicação
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
