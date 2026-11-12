# Dockerfile for Kavir Tire Purchase Bot
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tehran

# Set timezone and install ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Run as non-privileged user for security
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

# Default entrypoint runs the daily scheduler at 08:00 AM
CMD ["python", "tires_bot.py", "--mode", "daily", "--time", "08:00", "--workers", "3"]
