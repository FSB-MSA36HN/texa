FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY texa ./texa
COPY eval ./eval
RUN uv sync --frozen --no-dev
ENV TEXA_CATALOG=/app/catalog/ecommerce.yaml PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "texa.main:app", "--host", "0.0.0.0", "--port", "8000"]
