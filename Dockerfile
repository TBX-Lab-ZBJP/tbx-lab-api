FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MP_DB_PATH=/data/mp_mvp.sqlite3

RUN mkdir -p /data

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY agents ./agents
COPY mp_prompts ./mp_prompts
COPY knowledge_base ./knowledge_base
COPY sample_data ./sample_data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
