"""Document provision — plugins provide searchable documents for AI.

Plugins that implement ``DocumentMixin`` expose documents that AI can
discover, search, and read. Documents are available via:

- MCP resources (``resources/list``, ``resources/read``)
- HTTP: ``GET /api/plugins/{plugin_id}/documents/{uri}``

Set ``"documents": true`` in the manifest to enable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentDef:
    """Definition of a document provided by a plugin."""

    uri: str  # unique ID: plugin://{plugin_id}/{doc_name}
    name: str
    description: str = ""
    mime_type: str = "text/plain"
    content: str = ""  # static content (if known at define time)
    content_fn: str = ""  # method name on plugin for dynamic content


class DocumentMixin:
    """Mixin for plugins that provide searchable documents.

    Example::

        class MyPlugin(PluginBase, DocumentMixin):
            def get_documents(self) -> list[DocumentDef]:
                return [
                    DocumentDef(
                        uri="plugin://my-plugin/status",
                        name="System Status",
                        description="Current system health metrics",
                        content_fn="get_status_doc",
                    ),
                ]

            def get_status_doc(self) -> str:
                return f"CPU: {self.cpu_temp}°C, Memory: {self.mem_pct}%"
    """

    def get_documents(self) -> list[DocumentDef]:
        """Return document definitions. Called on activate and on refresh."""
        return []
