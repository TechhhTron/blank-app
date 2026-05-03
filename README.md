# Tradematic

Algorithmic trading SaaS platform with a Streamlit member dashboard and FastAPI backend.

## Local Setup

1. Create and activate a Python virtual environment.
2. Install backend dependencies:

```powershell
pip install -r backend/requirements.txt
```

3. Copy backend environment settings:

```powershell
Copy-Item backend\.env.example backend\.env
```

4. Update `backend\.env` with local secrets and broker settings.
5. Start the FastAPI backend:

```powershell
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

6. Start the Streamlit frontend:

```powershell
streamlit run app.py --server.port 8502
```

## Security Notes

- Do not commit `.env` files.
- Store API keys, broker secrets, and app secrets only in environment variables.
- The local SQLite database is ignored by Git.
