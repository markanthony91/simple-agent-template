FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY . .

RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 2024

CMD ["sh", "-c", "langgraph dev --host 0.0.0.0 --port ${PORT:-2024} --no-browser"]
