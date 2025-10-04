FROM python:3.11-slim

ARG VERSION=0.0.0-dev

ENV MCP_SERVER_VERSION=$VERSION \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY dhl_mcp_server.py /app/dhl_mcp_server.py

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir fastmcp requests

CMD ["fastmcp", "run", "dhl_mcp_server.py"]
