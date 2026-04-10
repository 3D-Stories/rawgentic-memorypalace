FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY rawgentic_memory/ rawgentic_memory/

RUN pip install --no-cache-dir .

# Match the frontend image's app user (uid=999) so shared volumes are accessible
RUN groupadd -g 999 app && useradd -r -u 999 -g app app
RUN mkdir -p /home/app/.mempalace/palace && chown -R app:app /home/app
USER app

EXPOSE 8420

# Disable idle timeout in Docker (run as persistent service)
# Bind to 0.0.0.0 so other containers and hosts can reach it
CMD ["python", "-m", "rawgentic_memory.server", "--host", "0.0.0.0", "--timeout", "0"]
