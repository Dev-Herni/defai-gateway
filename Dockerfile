# =============================================================================
# DeFAI Gateway — Multi-stage Docker Build
# =============================================================================
# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.12-slim AS runtime

# Add non-root user
RUN groupadd -r defai && useradd -r -g defai -d /app -s /sbin/nologin defai

WORKDIR /app

# Copy only installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application
COPY server.py .

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from web3 import Web3; w3 = Web3(Web3.HTTPProvider('${RPC_URL:-https://mainnet.base.org}')); exit(0 if w3.is_connected() else 1)" || exit 1

# Labels
LABEL org.opencontainers.image.title="DeFAI Gateway"
LABEL org.opencontainers.image.description="AI Agent Gateway to Base Chain DeFi — MCP Server"
LABEL org.opencontainers.image.source="https://github.com/Dev-Herni/defai-gateway"
LABEL org.opencontainers.image.licenses="MIT"

# Default: stdio mode for MCP
ENTRYPOINT ["python", "server.py"]

# Override with --http for SSE mode: python server.py --http 8080
# Override with --x402 for x402 payment gateway: python server.py --x402 4020
