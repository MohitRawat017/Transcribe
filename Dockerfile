FROM python:3.12-slim
WORKDIR /app
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY blog/blogify.py blog/publish.py config.yaml ./
# scripts are invoked via `docker compose run`; default just shows help
CMD ["python", "blogify.py", "--help"]
