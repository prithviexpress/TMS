FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY shared/ /shared/
RUN uv pip install --system --no-cache -e /shared
COPY services/vendor-service/pyproject.toml .
RUN uv pip install --system --no-cache -e .
COPY services/vendor-service/ .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
