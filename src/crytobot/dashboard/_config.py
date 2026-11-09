"""Pano konfigürasyon veri yapısı ve doğrulama (spec 0031 R-1, R-3, AC-1, AC-8)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})


@dataclass(frozen=True)
class DashboardConfig:
    """Pano ayarları: yalnızca localhost / 127.0.0.1'e bağlanır."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


@dataclass(frozen=True)
class DashboardConfigResult:
    """`config` ayarlar geçerliyse dolu; değilse `setting` ilk sorunlu ayarın adıdır."""

    config: DashboardConfig | None
    setting: str | None
    message: str


def load_dashboard_config(raw_config: Mapping[str, Any] | None = None) -> DashboardConfigResult:
    """[dashboard] ayarlarını yükler ve doğrular.

    Bölüm yoksa varsayılanlarla (127.0.0.1:8080) döner.
    Port int (1..65535), host yalnızca '127.0.0.1' veya 'localhost' olabilir.
    """
    if raw_config is None:
        return DashboardConfigResult(DashboardConfig(), None, "ayarlar geçerli")

    if not isinstance(raw_config, Mapping):
        return DashboardConfigResult(None, "dashboard", "ayar geçersiz: dashboard")

    dashboard_section = raw_config.get("dashboard")
    if dashboard_section is None:
        return DashboardConfigResult(DashboardConfig(), None, "ayarlar geçerli")

    if not isinstance(dashboard_section, Mapping):
        return DashboardConfigResult(None, "dashboard", "ayar geçersiz: dashboard")

    allowed_keys = {"host", "port"}
    for key in dashboard_section:
        if key not in allowed_keys:
            return DashboardConfigResult(
                None, f"dashboard.{key}", f"bilinmeyen ayar: dashboard.{key}"
            )

    host = dashboard_section.get("host", DEFAULT_HOST)
    if not isinstance(host, str) or host not in ALLOWED_HOSTS:
        return DashboardConfigResult(None, "dashboard.host", "ayar geçersiz: dashboard.host")

    port_val = dashboard_section.get("port", DEFAULT_PORT)
    if type(port_val) is not int or not (1 <= port_val <= 65535):
        return DashboardConfigResult(None, "dashboard.port", "ayar geçersiz: dashboard.port")

    return DashboardConfigResult(DashboardConfig(host=host, port=port_val), None, "ayarlar geçerli")
