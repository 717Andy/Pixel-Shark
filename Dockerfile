FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PIXELSHARK_HOST=0.0.0.0 \
    PIXELSHARK_PORT=8000 \
    PIXELSHARK_AUTOPLAY=1

COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages

RUN uv sync --frozen --no-dev --package pixelshark-table

EXPOSE 8000
CMD ["pixelshark-table", "--host", "0.0.0.0", "--port", "8000"]
