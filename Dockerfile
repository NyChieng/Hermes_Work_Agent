FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create persistent data directory for SQLite
RUN mkdir -p /app/data

# Override DB_PATH at runtime via env var (see db.py)
ENV DB_PATH=/app/data/tasks.db

EXPOSE 8000

CMD ["python", "main.py"]
