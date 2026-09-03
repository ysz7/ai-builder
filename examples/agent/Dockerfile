# The image this project runs as. A node on the graph, and never regenerated from it.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/

CMD ["python", "-c", "import agent; print(agent.run('today:'))"]
