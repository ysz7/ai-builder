# The image this project runs as. A node on the graph, and never regenerated from it: the
# file is the source of truth, exactly as every .py in here is.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY rag/ ./rag/

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
