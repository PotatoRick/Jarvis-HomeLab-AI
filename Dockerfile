FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (LOW-005 FIX: Add curl for healthcheck)
RUN apt-get update && apt-get install -y \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Copy runbooks (Phase 4)
COPY runbooks/ ./runbooks/

# Create directory for SSH keys
RUN mkdir -p /app/ssh-keys && chmod 700 /app/ssh-keys

# Create non-root user
RUN useradd -m -u 1000 remediation && \
    chown -R remediation:remediation /app

USER remediation

# Expose port
EXPOSE 8000

# Health check (LOW-005 FIX: Use curl instead of httpx for reliability)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
