"""App catalog — predefined templates for hosted web apps.

Each template defines the Docker image, ports, environment, data paths,
and resource limits for a specific application. The catalog is expandable
by adding new entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AppTemplate:
    """A template for a hosted web app."""

    app_type: str
    label: str
    description: str
    image: str
    port: int
    icon: str
    data_path: str
    memory: str = "512m"
    cpus: str = "1"
    env: dict[str, str] = field(default_factory=dict)
    # Some images run as root internally — override user if needed
    user: str = ""
    # Extra docker flags
    extra_args: list[str] = field(default_factory=list)


CATALOG: dict[str, AppTemplate] = {
    "n8n": AppTemplate(
        app_type="n8n",
        label="n8n",
        description="Workflow automation — connect APIs, schedule tasks, build AI chains",
        image="openhort/n8n-python:latest",
        port=5678,
        icon="ph ph-flow-arrow",
        data_path="/home/node/.n8n",
        memory="1g",
        cpus="2",
        env={
            "N8N_SECURE_COOKIE": "false",
            "N8N_DIAGNOSTICS_ENABLED": "false",
            "N8N_PERSONALIZATION_ENABLED": "false",
            "N8N_USER_MANAGEMENT_DISABLED": "true",
            "N8N_PUBLIC_API_DISABLED": "false",
            "N8N_HIRING_BANNER_ENABLED": "false",
            "N8N_TEMPLATES_ENABLED": "true",
            "N8N_EDITOR_BASE_URL": "",
            "N8N_ENCRYPTION_KEY": "openhort-n8n-stable-encryption-key",
        },
    ),
    "code-server": AppTemplate(
        app_type="code-server",
        label="VS Code",
        description="Full VS Code editor in the browser",
        image="codercom/code-server:latest",
        port=8080,
        icon="ph ph-code",
        data_path="/home/coder",
        memory="1g",
        cpus="2",
        env={"PASSWORD": ""},  # no password, openhort handles auth
        extra_args=["--bind-addr", "0.0.0.0:8080", "--auth", "none"],
    ),
    "jupyter": AppTemplate(
        app_type="jupyter",
        label="Jupyter Lab",
        description="Interactive notebooks for Python, data science, ML",
        image="jupyter/minimal-notebook:latest",
        port=8888,
        icon="ph ph-notebook",
        data_path="/home/jovyan/work",
        memory="1g",
        cpus="2",
        env={"JUPYTER_TOKEN": ""},  # no token, openhort handles auth
    ),
    "homeassistant": AppTemplate(
        app_type="homeassistant",
        label="Home Assistant",
        description="Smart home automation and IoT hub",
        image="ghcr.io/home-assistant/home-assistant:stable",
        port=8123,
        icon="ph ph-house-line",
        data_path="/config",
        memory="512m",
        cpus="1",
        user="",  # runs as root internally
    ),
    "excalidraw": AppTemplate(
        app_type="excalidraw",
        label="Excalidraw",
        description="Virtual whiteboard for sketching and diagramming",
        image="excalidraw/excalidraw:latest",
        port=80,
        icon="ph ph-pencil-line",
        data_path="/app/data",
        memory="256m",
        cpus="0.5",
    ),
}


def get_catalog() -> dict[str, dict[str, Any]]:
    """Return catalog as dicts for API/UI consumption."""
    return {
        k: {
            "app_type": t.app_type,
            "label": t.label,
            "description": t.description,
            "icon": t.icon,
            "image": t.image,
        }
        for k, t in CATALOG.items()
    }
