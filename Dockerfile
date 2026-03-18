FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (if any – none needed for SQLite)
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a directory for the SQLite database (will be overridden by volume)
RUN mkdir -p /data

# Use an environment variable to set the database path
ENV SQLITE_DB_PATH=/data/surveillance.db

# Run the app with uvicorn, binding to 0.0.0.0 and the port Fly expects (8080)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
