"""Spec 0031 AC-4, AC-5 (R-5): Pano HTML arayüzü, responsive tasarım, CDN yokluğu ve
yenileme testleri.
"""

from crytobot.dashboard import render_dashboard_html


def test_dashboard_html_offline_and_responsive() -> None:
    html = render_dashboard_html()

    # AC-4: Responsive ve HTML5 yapısı
    assert "<!DOCTYPE html>" in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "CrytoBot Pano" in html

    # AC-4: Koyu tema (dark mode) ve WCAG renkleri
    assert "--bg: #0b0f19;" in html
    assert "--card-bg: #151d2f;" in html
    assert "--text-main: #f1f5f9;" in html

    # AC-4: Rozetler ve metrik alanları
    assert 'id="badge-process"' in html
    assert 'id="badge-mode"' in html
    assert 'id="badge-halt"' in html
    assert 'id="metric-equity"' in html
    assert 'id="metric-free"' in html
    assert 'id="metric-pnl"' in html
    assert 'id="metric-peak"' in html
    assert 'id="metric-drawdown"' in html

    # AC-4: Açık pozisyonlar tablosu ve alanları
    assert 'id="positions-table"' in html
    assert "Çift" in html
    assert "Yön" in html
    assert "Miktar" in html
    assert "Giriş Fiyatı" in html
    assert "Güncel Fiyatı" in html or "Güncel Fiyat" in html
    assert "Stop-Loss" in html
    assert "Hedef Fiyat" in html

    # AC-4: Harici CDN veya internet bağlantısı bağımlılığı OLMAMALI (tamamen çevrimdışı)
    assert "http://" not in html
    assert "https://" not in html
    assert '<link rel="stylesheet" href="http' not in html
    assert '<script src="http' not in html
    assert "cdn." not in html.lower()
    assert "unpkg.com" not in html
    assert "cdnjs" not in html


def test_auto_refresh_and_manual_refresh() -> None:
    html = render_dashboard_html()

    # AC-5: 5 saniyelik otomatik yenileme ve elle yenileme butonu
    assert 'id="btn-refresh"' in html
    assert 'id="countdown-text"' in html
    assert 'fetch("/api/status")' in html
    assert "let countdown = 5;" in html
    assert "setInterval(tick, 1000);" in html
    assert 'addEventListener("click"' in html


def test_logs_rendering_escapes_html_using_text_content() -> None:
    html = render_dashboard_html()

    # Finding 1: Loglar HTML kaçışı için textContent ile güvenli eklenir
    assert "item.textContent = l" in html
    assert "createElement" in html


def test_live_mode_line_is_text() -> None:
    """Spec 0035 AC-4 (R-3): canlı mod ilk satırda metin olarak yazılır; renk yalnız ek."""
    html = render_dashboard_html()
    body = html[html.index("<body>") :]
    container = body[body.index('<div class="container">') :]
    first_element = container.split("\n")[1].strip()
    assert first_element.startswith('<div id="mode-banner"')
    assert '"CANLI MOD — gerçek para"' in html
    assert 'modeBanner.textContent = "CANLI MOD — gerçek para"' in html
    assert 'modeWarning.textContent = "UYARI: " + data.mode_mismatch' in html
    assert "innerHTML" not in html.split("// Spec 0035 R-3")[1].split("haltBadge")[0]


def test_testnet_badge() -> None:
    """Spec 0041 CB-5, G-3: TESTNET rozeti metindir, başta gizlidir ve yalnız `network` alanı
    `testnet` iken gösterilir; gizli rozet `.badge`'in görünürlüğüyle açılmaz."""
    html = render_dashboard_html()

    assert '<span id="badge-network" class="badge badge-network" hidden>TESTNET</span>' in html
    assert ".badge[hidden] { display: none; }" in html
    assert 'getElementById("badge-network").hidden = data.network !== "testnet";' in html
    # the live banner text is unchanged on either network (PB-1)
    assert 'modeBanner.textContent = "CANLI MOD — gerçek para"' in html
