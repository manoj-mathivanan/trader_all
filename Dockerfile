FROM python:3.13-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY core core
COPY strategies strategies
COPY dashboard dashboard
COPY reference_data reference_data
COPY scripts/sync_investor_data.py scripts/sync_market_refresh.py scripts/market_data_bundle.py scripts/
COPY deploy/market-data/import_investor_data.py deploy/market-data/export_investor_data.py deploy/market-data/investor_schema.sql deploy/market-data/
RUN useradd --uid 10001 --create-home trader
USER trader
CMD ["python", "-m", "uvicorn", "dashboard.api.main:app", "--host", "127.0.0.1", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
