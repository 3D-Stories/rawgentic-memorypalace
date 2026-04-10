"""Tests for the frontend Docker Compose configuration (Issue #13)."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
COMPOSE_FILE = PROJECT_ROOT / "frontend" / "docker-compose.yml"
ENV_EXAMPLE = PROJECT_ROOT / "frontend" / ".env.example"


def _load_compose():
    return yaml.safe_load(COMPOSE_FILE.read_text())


class TestComposeFileExists:
    """Validate frontend/ directory and docker-compose.yml exist."""

    def test_frontend_directory_exists(self):
        assert COMPOSE_FILE.parent.exists(), "Missing frontend/ directory"

    def test_compose_file_exists(self):
        assert COMPOSE_FILE.exists(), "Missing frontend/docker-compose.yml"

    def test_env_example_exists(self):
        assert ENV_EXAMPLE.exists(), "Missing frontend/.env.example"


class TestComposeServices:
    """AC1: Two frontend instances with correct service names."""

    def test_has_native_frontend_service(self):
        compose = _load_compose()
        assert "native-frontend" in compose["services"], (
            "Must define native-frontend service"
        )

    def test_has_mempalace_frontend_service(self):
        compose = _load_compose()
        assert "mempalace-frontend" in compose["services"], (
            "Must define mempalace-frontend service"
        )

    def test_exactly_two_services(self):
        compose = _load_compose()
        assert len(compose["services"]) == 2, (
            "Must have exactly 2 services (native + mempalace)"
        )


class TestPortMappings:
    """AC1: Correct port assignments — 8098 for native, 8099 for mempalace."""

    def test_native_frontend_port_8098(self):
        compose = _load_compose()
        ports = compose["services"]["native-frontend"]["ports"]
        port_strs = [str(p) for p in ports]
        assert any("8098" in p and "8099" in p for p in port_strs), (
            "native-frontend must map host 8098 to container 8099"
        )

    def test_mempalace_frontend_port_8099(self):
        compose = _load_compose()
        ports = compose["services"]["mempalace-frontend"]["ports"]
        port_strs = [str(p) for p in ports]
        assert any("8099" in p for p in port_strs), (
            "mempalace-frontend must map host 8099 to container 8099"
        )


class TestVolumeMounts:
    """AC3: Each instance mounts ChromaDB data as read-only."""

    def _get_volumes(self, service_name):
        compose = _load_compose()
        return compose["services"][service_name].get("volumes", [])

    def test_native_has_palace_volume(self):
        volumes = self._get_volumes("native-frontend")
        assert any("/app/palace" in v for v in volumes), (
            "native-frontend must mount data at /app/palace"
        )

    def test_mempalace_has_palace_volume(self):
        volumes = self._get_volumes("mempalace-frontend")
        assert any("/app/palace" in v for v in volumes), (
            "mempalace-frontend must mount data at /app/palace"
        )

    def test_native_volume_is_readonly(self):
        volumes = self._get_volumes("native-frontend")
        palace_vols = [v for v in volumes if "/app/palace" in v]
        assert palace_vols and all(":ro" in v for v in palace_vols), (
            "native-frontend palace volume must be read-only (:ro)"
        )

    def test_mempalace_volume_is_readonly(self):
        volumes = self._get_volumes("mempalace-frontend")
        palace_vols = [v for v in volumes if "/app/palace" in v]
        assert palace_vols and all(":ro" in v for v in palace_vols), (
            "mempalace-frontend palace volume must be read-only (:ro)"
        )


class TestHealthChecks:
    """Both services must have health checks."""

    def test_native_has_healthcheck(self):
        compose = _load_compose()
        assert "healthcheck" in compose["services"]["native-frontend"], (
            "native-frontend must define a healthcheck"
        )

    def test_mempalace_has_healthcheck(self):
        compose = _load_compose()
        assert "healthcheck" in compose["services"]["mempalace-frontend"], (
            "mempalace-frontend must define a healthcheck"
        )


class TestImageBuild:
    """Services must reference the frontend image with build capability."""

    def test_native_has_image_ref(self):
        compose = _load_compose()
        svc = compose["services"]["native-frontend"]
        assert "image" in svc or "build" in svc, (
            "native-frontend must have image or build reference"
        )

    def test_mempalace_has_image_ref(self):
        compose = _load_compose()
        svc = compose["services"]["mempalace-frontend"]
        assert "image" in svc or "build" in svc, (
            "mempalace-frontend must have image or build reference"
        )
