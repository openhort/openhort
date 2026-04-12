"""Microsoft 365 llming — Mail, Calendar, Teams, Files via office-connect.

Wraps the ``office-connect`` library to provide Microsoft 365 access
as a standard openhort llming with MCP tools and OAuth credential flow.

Requires:
- Azure AD app registration (client ID in config)
- OAuth2 authentication via the credential system
- office-connect library (``pip install office-connect``)
"""

from __future__ import annotations

import logging
from typing import Any

from hort.llming import Llming, Power, PowerType

logger = logging.getLogger(__name__)


class Office365Plugin(Llming):
    """Microsoft 365 llming — mail, calendar, teams, files."""

    _office: Any = None  # OfficeUserInstance, created after auth
    _config: dict[str, Any] = {}

    def activate(self, config: dict[str, Any]) -> None:
        self._config = config
        self.log.info("Office 365 plugin activated")
        # Don't connect yet — wait for credentials

    def _ensure_connected(self) -> bool:
        """Connect to MS Graph if we have valid credentials."""
        if self._office is not None:
            return True

        try:
            # Get credentials from the credential manager
            cred = None
            if self.credentials is not None:
                cred = self.credentials.get("ms_oauth")

            if not cred or "access_token" not in cred:
                return False

            from office_con import OfficeUserInstance
            self._office = OfficeUserInstance(
                access_token=cred["access_token"],
            )
            self.log.info("Connected to Microsoft 365")
            self.vault.set("state", {
                "connected": True,
                "tenant": self._config.get("tenant", ""),
            })
            return True
        except ImportError:
            self.log.warning("office-connect not installed")
            return False
        except Exception:
            self.log.exception("Failed to connect to Microsoft 365")
            return False

    def get_pulse(self) -> dict[str, Any]:
        return {
            "connected": self._office is not None,
            "tenant": self._config.get("tenant", ""),
        }

    # ===== MCP Tools =====

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="list_emails",
                type=PowerType.MCP,
                description="List recent emails from inbox",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                        "folder": {"type": "string", "default": "inbox"},
                    },
                },
            ),
            Power(
                name="read_email",
                type=PowerType.MCP,
                description="Read a specific email by ID",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                    },
                    "required": ["message_id"],
                },
            ),
            Power(
                name="send_email",
                type=PowerType.MCP,
                description="Send an email",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
            ),
            Power(
                name="list_events",
                type=PowerType.MCP,
                description="List upcoming calendar events",
                input_schema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 7},
                    },
                },
            ),
            Power(
                name="list_files",
                type=PowerType.MCP,
                description="List files in OneDrive",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "/"},
                    },
                },
            ),
        ]

    async def execute_power(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._ensure_connected():
            # Request credential update
            if self.credentials is not None:
                self.credentials.request_update(
                    "ms_oauth", "Microsoft account not authenticated",
                )
            return {"error": "Not authenticated. Set up Microsoft credentials first."}

        try:
            if name == "list_emails":
                messages = self._office.get_messages(
                    limit=arguments.get("limit", 10),
                    folder=arguments.get("folder", "inbox"),
                )
                return {"emails": [
                    {"id": m.id, "subject": m.subject, "from": str(m.sender), "date": str(m.received)}
                    for m in messages
                ]}

            elif name == "read_email":
                msg = self._office.get_message(arguments["message_id"])
                return {
                    "subject": msg.subject,
                    "from": str(msg.sender),
                    "body": msg.body,
                    "date": str(msg.received),
                }

            elif name == "send_email":
                self._office.send_message(
                    to=arguments["to"],
                    subject=arguments["subject"],
                    body=arguments["body"],
                )
                return {"ok": True, "message": f"Email sent to {arguments['to']}"}

            elif name == "list_events":
                events = self._office.get_events(days=arguments.get("days", 7))
                return {"events": [
                    {"subject": e.subject, "start": str(e.start), "end": str(e.end)}
                    for e in events
                ]}

            elif name == "list_files":
                files = self._office.list_files(path=arguments.get("path", "/"))
                return {"files": [
                    {"name": f.name, "size": f.size, "type": f.type}
                    for f in files
                ]}

        except Exception:
            self.log.exception("MCP tool error: %s", name)
            return {"error": "Something went wrong."}

        return {"error": f"Unknown tool: {name}"}

    def deactivate(self) -> None:
        self._office = None
