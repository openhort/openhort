"""WS command modules — each domain registers handlers on a WSRouter.

Assembled into a root router in ``build_ws_router()`` and mounted
on the controller at startup.

Message types are dot-namespaced: ``llmings.list``, ``config.get``, etc.
"""

from llming_com import WSRouter


def build_ws_router() -> WSRouter:
    """Assemble all command routers into a single root router."""
    from hort.commands.llmings import router as llmings_router
    from hort.commands.config import router as config_router
    from hort.commands.connectors import router as connectors_router
    from hort.commands.credentials import router as credentials_router
    from hort.commands.settings import router as settings_router
    from hort.commands.sources import router as sources_router
    from hort.commands.debug import router as debug_router
    from hort.commands.cam import router as cam_router
    from hort.commands.wire import router as wire_router

    root = WSRouter()
    root.include(llmings_router)
    root.include(config_router)
    root.include(connectors_router)
    root.include(credentials_router)
    root.include(settings_router)
    root.include(sources_router)
    root.include(debug_router)
    root.include(cam_router)
    root.include(wire_router)
    return root
