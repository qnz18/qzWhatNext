# Dockerfile for Google Cloud Run deployment

FROM python:3.9-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY qzwhatnext/ ./qzwhatnext/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "qzwhatnext.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

