# Railway runtime image
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY . .

RUN uv sync --no-dev
RUN uv pip install --python .venv/bin/python "langchain-openai>=1.4.0,<2.0.0"

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 2024

CMD ["sh", "-c", "langgraph dev --host 0.0.0.0 --port ${PORT:-2024} --no-browser"]
