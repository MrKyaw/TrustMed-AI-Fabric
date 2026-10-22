FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

ENV TRUSTMED_DB_PATH=/data/trustmed.db
ENV TRUSTMED_REPORT_DIR=/data/reports
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "trustmed_fabric.api:get_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
