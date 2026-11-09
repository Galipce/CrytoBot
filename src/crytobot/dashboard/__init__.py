"""Pano (dashboard) modülü: localhost salt-okunur web izleme panosu (spec 0031).

Yalnızca 127.0.0.1 üzerinde çalışır. Host denetimi yapar, GET dışı metotları ve
DNS rebinding girişimlerini reddeder. Control veya execution bağımlılığı taşımaz (ADR 0002).
"""

from crytobot.dashboard._config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DashboardConfig,
    DashboardConfigResult,
    load_dashboard_config,
)
from crytobot.dashboard._html import render_dashboard_html
from crytobot.dashboard._server import (
    DashboardHandler,
    DashboardServer,
    PortBusyError,
    StatusProvider,
    create_server,
)

__all__: list[str] = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DashboardConfig",
    "DashboardConfigResult",
    "DashboardHandler",
    "DashboardServer",
    "PortBusyError",
    "StatusProvider",
    "create_server",
    "load_dashboard_config",
    "render_dashboard_html",
]
