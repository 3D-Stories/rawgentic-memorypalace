FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY rawgentic_memory/ rawgentic_memory/

RUN pip install --no-cache-dir .

EXPOSE 8420

# Disable idle timeout in Docker (run as persistent service)
# Bind to 0.0.0.0 so other containers and hosts can reach it
CMD ["python", "-m", "rawgentic_memory.server", "--host", "0.0.0.0", "--timeout", "0"]
