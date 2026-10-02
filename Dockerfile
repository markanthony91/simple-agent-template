# Railway runtime image
FROM python:3.12-slim

WORKDIR /app

RUN env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy pip install --no-cache-dir uv

COPY . .

RUN env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy uv sync --frozen --no-dev \
    && .venv/bin/python scripts/patch_checkpoint_reads.py \
    && .venv/bin/python scripts/patch_runtime_queue_poll.py

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 2024

ENTRYPOINT ["python", "-m", "simple_agent.startup"]
CMD ["sh", "-c", "if [ \"${OSS_RUNTIME_ENABLED:-false}\" = true ]; then exec uvicorn simple_agent.oss_runtime:app --host 0.0.0.0 --port ${PORT:-2024}; else exec langgraph dev --host 0.0.0.0 --port ${PORT:-2024} --no-browser --n-jobs-per-worker ${LANGGRAPH_N_JOBS_PER_WORKER:-1}; fi"]
