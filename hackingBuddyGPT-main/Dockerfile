# Use official Python image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Ensure local src/ is importable when running from source
ENV PYTHONPATH=/app/src

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app/

# Install Python dependencies
RUN pip install --upgrade pip \
    && pip install -e .

# Expose port for web UI (if needed)
EXPOSE 4444

# Default command (can be overridden)
ENTRYPOINT ["python", "src/hackingBuddyGPT/cli/wintermute.py"]
CMD ["--help"]
