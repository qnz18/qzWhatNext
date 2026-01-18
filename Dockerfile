# Dockerfile for Google Cloud Run deployment

FROM python:3.9-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY qzwhatnext/ ./qzwhatnext/

# Expose port (Cloud Run will set PORT env var, default to 8000 for local dev)
EXPOSE 8000

# Run the application - use PORT env var from Cloud Run or default to 8000
# Use shell form to allow variable substitution
CMD sh -c "uvicorn qzwhatnext.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"

