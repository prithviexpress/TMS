FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir uv

# Install shared library first (build context = TMS root)
COPY shared/ /shared/
RUN uv pip install --system --no-cache -e /shared

# Install service dependencies
COPY services/schedule-service/pyproject.toml .
RUN uv pip install --system --no-cache -e .

# Copy service source
COPY services/schedule-service/ .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
