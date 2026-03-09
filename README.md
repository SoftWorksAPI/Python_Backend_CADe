# Python_Backend_CADe
Backend Python do "CADê", Projeto do 4° Semestre de ADS em 2026

### 1. Clone o Repositório (opcional)
Se você ainda não clonou o repositório, use o comando abaixo:
```bash
git clone https://github.com/seu-usuario/Python_Backend_CADe.git
cd Python_Backend_CADe
```

### 2. Crie um Ambiente Virtual
Crie um ambiente virtual para isolar as dependências do projeto:
```bash
python -m venv venv
```

Ative o ambiente virtual:
- **Windows**:
  ```bash
  .\venv\Scripts\activate
  ```
- **Linux/Mac**:
  ```bash
  source venv/bin/activate
  ```

### 3. Instale as Dependências
Com o ambiente virtual ativado, instale as dependências do projeto:
```bash
pip install -r requirements.txt
```

### 4. Execute o Servidor FastAPI
Inicie o servidor de desenvolvimento do FastAPI:
```bash
uvicorn main:app --reload
```

- O servidor estará disponível em: [http://127.0.0.1:8000](http://127.0.0.1:8000)