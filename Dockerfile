# One image, two entrypoints (gateway / mcp). Non-root, no build tools at runtime.
# bookworm pinned: Microsoft's ODBC repo below targets Debian 12
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Microsoft ODBC Driver 18 for SQL Server
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY gateway ./gateway
COPY mcp_server ./mcp_server
RUN mkdir -p /app/keys /app/data && chown app:app /app/keys /app/data
USER app

EXPOSE 8000 8001
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
