# Railway runtime image
FROM python:3.12-slim

WORKDIR /app

RUN env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy pip install --no-cache-dir uv

COPY . .

RUN env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 2024

ENTRYPOINT ["python", "-m", "simple_agent.startup"]
CMD ["sh", "-c", "langgraph dev --host 0.0.0.0 --port ${PORT:-2024} --no-browser"]
