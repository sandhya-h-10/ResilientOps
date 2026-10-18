FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
COPY web2 ./web2
COPY resilientops_data ./resilientops_data
RUN uv sync --frozen --no-dev --extra google --extra mcp
ENV PATH="/app/.venv/bin:$PATH" \
    RESILIENTOPS_DATA_DIR="/app/resilientops_data" \
    RESILIENTOPS_DB="/app/var/operational.db"
RUN useradd --uid 10001 --create-home appuser && mkdir /app/var && chown appuser /app/var
USER appuser
EXPOSE 8000
CMD ["resilientops", "serve", "--host", "0.0.0.0", "--port", "8000"]
