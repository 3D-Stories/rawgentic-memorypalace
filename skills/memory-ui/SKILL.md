---
name: rawgentic-memorypalace:memory-ui
description: Start, stop, or check status of the web frontend containers for browsing memory data.
argument-hint: up | down | status
---

<role>
You are the memory UI management assistant. Your job is to manage the Docker Compose frontend containers that provide a web interface for browsing memory palace data.
</role>

# /memory-ui — Web Frontend Management

Manage the dual web frontend instances for browsing memory backend data.

- **Native frontend:** http://localhost:8098 (native ChromaDB backend)
- **MemPalace frontend:** http://localhost:8099 (MemPalace backend)

## Usage

```
/memory-ui up       Start both frontend containers
/memory-ui down     Stop both frontend containers
/memory-ui status   Show container state, ports, and uptime
```

## Instructions

### 1. Parse Subcommand

Check the first word of the arguments:

- **`up`** -> go to Section 3
- **`down`** -> go to Section 4
- **`status`** -> go to Section 5
- **No arguments or unrecognized** -> show usage above and STOP

### 2. Pre-flight Check — Docker Availability

Before executing any subcommand, verify Docker is available:

```bash
docker compose version 2>&1
```

**If the command fails (exit code non-zero):**

```
Docker is not installed or not running.

To fix:
1. Install Docker: https://docs.docker.com/get-docker/
2. Start the Docker daemon: sudo systemctl start docker
3. Ensure your user is in the docker group: sudo usermod -aG docker $USER
```

STOP after showing the error. Do NOT attempt to install Docker.

### 3. Subcommand: `up` — Start Frontends

1. Check if the `.env` file exists:

```bash
ls frontend/.env 2>/dev/null
```

If missing, warn the user:

```
No frontend/.env file found. Creating from template...
```

Then copy it:

```bash
cp frontend/.env.example frontend/.env
```

Tell the user to review and edit `frontend/.env` if the default paths are wrong, especially `NATIVE_CHROMADB_PATH` which is required.

2. Start the containers:

```bash
docker compose -f frontend/docker-compose.yml up -d --build 2>&1
```

3. Check that containers started:

```bash
docker compose -f frontend/docker-compose.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>&1
```

4. Report the result:

**If both containers are running:**

```
Web frontends are up:
- Native backend browser:    http://localhost:8098
- MemPalace backend browser: http://localhost:8099

First run builds the image (~2 min). Subsequent starts are fast.
```

**If containers failed to start:** Show the docker compose output and suggest checking `docker compose -f frontend/docker-compose.yml logs`.

### 4. Subcommand: `down` — Stop Frontends

1. Stop the containers:

```bash
docker compose -f frontend/docker-compose.yml down 2>&1
```

2. Confirm:

```
Web frontends stopped.
```

### 5. Subcommand: `status` — Show Container State

1. Query container status:

```bash
docker compose -f frontend/docker-compose.yml ps --format json 2>&1
```

2. **If containers are running:** Display a table:

```
## Memory UI Status

| Container | State | Ports | Uptime |
|-----------|-------|-------|--------|
| rawgentic-native-frontend   | running | 127.0.0.1:8098->8099 | 2 hours |
| rawgentic-mempalace-frontend | running | 127.0.0.1:8099->8099 | 2 hours |

- Native backend browser:    http://localhost:8098
- MemPalace backend browser: http://localhost:8099
```

Parse the JSON output to extract Name, State, Ports, and compute uptime from the status field.

3. **If containers are not running:**

```
Web frontends are not running.

Start them with: /memory-ui up
```

STOP after displaying status. Do NOT start containers automatically.
