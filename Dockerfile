FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .

RUN useradd --create-home --shell /usr/sbin/nologin datapilot \
    && mkdir -p /app/.datapilot \
    && chown -R datapilot:datapilot /app
USER datapilot

EXPOSE 8501 8000

CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
