"""Pano HTML şablonu (spec 0031 R-5, AC-4, AC-5).

Modern, koyu temalı (dark mode), harici CDN veya ağ bağımlılığı içermeyen tek sayfa arayüzü.
Sistem durum rozetleri, finansal metrik kartları, açık pozisyonlar tablosu, son tur özeti,
5 saniyede bir otomatik yenileme (polling) ve elle yenileme butonu içerir.
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CrytoBot Pano</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151d2f;
      --card-border: #243049;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --green: #10b981;
      --green-bg: rgba(16, 185, 129, 0.15);
      --red: #f43f5e;
      --red-bg: rgba(244, 63, 94, 0.15);
      --amber: #f59e0b;
      --amber-bg: rgba(245, 158, 11, 0.15);
      --gray: #64748b;
      --gray-bg: rgba(100, 116, 139, 0.2);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      line-height: 1.5;
      padding: 1.5rem;
    }
    .container { max-width: 1200px; margin: 0 auto; }
    header {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      margin-bottom: 2rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--card-border);
    }
    .header-title { display: flex; align-items: center; gap: 0.75rem; }
    h1 { font-size: 1.5rem; font-weight: 700; color: #fff; letter-spacing: -0.025em; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.375rem;
      padding: 0.25rem 0.625rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge-running {
      background-color: var(--green-bg);
      color: var(--green);
      border: 1px solid var(--green);
    }
    .badge-stopped {
      background-color: var(--gray-bg);
      color: var(--gray);
      border: 1px solid var(--gray);
    }
    .badge-mode {
      background-color: rgba(59, 130, 246, 0.15);
      color: var(--accent);
      border: 1px solid var(--accent);
    }
    .badge-halt-none {
      background-color: var(--green-bg);
      color: var(--green);
    }
    .badge-halt-kill {
      background-color: var(--red-bg);
      color: var(--red);
      border: 1px solid var(--red);
    }
    .badge-halt-drawdown {
      background-color: var(--amber-bg);
      color: var(--amber);
      border: 1px solid var(--amber);
    }
    .controls { display: flex; align-items: center; gap: 1rem; }
    .refresh-btn {
      background-color: var(--accent);
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 0.5rem 1rem;
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.375rem;
      transition: background-color 0.15s ease;
    }
    .refresh-btn:hover { background-color: var(--accent-hover); }
    .countdown { font-size: 0.8125rem; color: var(--text-muted); }
    .banner {
      display: none;
      padding: 1rem;
      border-radius: 8px;
      margin-bottom: 1.5rem;
      font-weight: 500;
    }
    .banner-error {
      background-color: var(--red-bg);
      border: 1px solid var(--red);
      color: #fecdd3;
    }
    .grid-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }
    .card {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 1.25rem;
    }
    .card-label {
      font-size: 0.8125rem;
      color: var(--text-muted);
      margin-bottom: 0.5rem;
      font-weight: 500;
    }
    .card-value { font-size: 1.5rem; font-weight: 700; color: #fff; }
    .card-subtext { font-size: 0.8125rem; margin-top: 0.375rem; color: var(--text-muted); }
    .val-positive { color: var(--green); }
    .val-negative { color: var(--red); }
    .progress-bar-bg {
      background-color: rgba(255, 255, 255, 0.1);
      border-radius: 9999px;
      height: 6px;
      margin-top: 0.5rem;
      overflow: hidden;
    }
    .progress-bar-fill {
      height: 100%;
      background-color: var(--amber);
      border-radius: 9999px;
      width: 0%;
      transition: width 0.3s ease;
    }
    .section-title {
      font-size: 1.125rem;
      font-weight: 600;
      color: #fff;
      margin-bottom: 1rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .table-container {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      overflow-x: auto;
      margin-bottom: 2rem;
    }
    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.875rem; }
    th {
      background-color: rgba(0, 0, 0, 0.2);
      color: var(--text-muted);
      padding: 0.75rem 1rem;
      font-weight: 600;
      border-bottom: 1px solid var(--card-border);
      white-space: nowrap;
    }
    td {
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--card-border);
      white-space: nowrap;
    }
    tr:last-child td { border-bottom: none; }
    .empty-state {
      padding: 2.5rem;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.9375rem;
    }
    .info-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }
    .log-box {
      background-color: rgba(0, 0, 0, 0.25);
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 0.75rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.8125rem;
      color: #cbd5e1;
      max-height: 160px;
      overflow-y: auto;
    }
    .log-item { margin-bottom: 0.25rem; }
    footer {
      text-align: center;
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 2rem;
      padding-top: 1rem;
      border-top: 1px solid var(--card-border);
    }
  </style>
</head>
<body>
  <div class="container">
    <div id="error-banner" class="banner banner-error"></div>

    <header>
      <div class="header-title">
        <h1>CrytoBot</h1>
        <span id="badge-process" class="badge badge-stopped">Durdu</span>
        <span id="badge-mode" class="badge badge-mode">paper</span>
        <span id="badge-halt" class="badge badge-halt-none">Normal</span>
      </div>
      <div class="controls">
        <span id="countdown-text" class="countdown">Yenileniyor: 5s</span>
        <button id="btn-refresh" class="refresh-btn">
          <span>Yenile</span>
        </button>
      </div>
    </header>

    <main>
      <section class="grid-metrics">
        <div class="card">
          <div class="card-label">Toplam Kasa</div>
          <div id="metric-equity" class="card-value">—</div>
          <div class="card-subtext">USDT</div>
        </div>
        <div class="card">
          <div class="card-label">Serbest Bakiye</div>
          <div id="metric-free" class="card-value">—</div>
          <div class="card-subtext">USDT</div>
        </div>
        <div class="card">
          <div class="card-label">Günlük Kâr / Zarar</div>
          <div id="metric-pnl" class="card-value">—</div>
          <div id="metric-pnl-pct" class="card-subtext">—</div>
        </div>
        <div class="card">
          <div class="card-label">Zirve Kasa</div>
          <div id="metric-peak" class="card-value">—</div>
          <div class="card-subtext">USDT</div>
        </div>
        <div class="card">
          <div class="card-label">Drawdown Oranı</div>
          <div id="metric-drawdown" class="card-value">0.00%</div>
          <div class="progress-bar-bg">
            <div id="metric-drawdown-bar" class="progress-bar-fill"></div>
          </div>
        </div>
      </section>

      <section>
        <div class="section-title">Açık Pozisyonlar (<span id="pos-count">0</span>)</div>
        <div class="table-container">
          <table id="positions-table">
            <thead>
              <tr>
                <th>Çift</th>
                <th>Yön</th>
                <th>Miktar</th>
                <th>Giriş Fiyatı</th>
                <th>Güncel Fiyat</th>
                <th>Stop-Loss</th>
                <th>Hedef Fiyat</th>
                <th>Kâr / Zarar</th>
              </tr>
            </thead>
            <tbody id="positions-body">
              <tr>
                <td colspan="8" class="empty-state">Açık pozisyon yok</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="info-grid">
        <div class="card">
          <div class="section-title">Son Tur Durumu</div>
          <div style="font-size: 0.875rem;">
            <p style="margin-bottom: 0.5rem;">
              <strong>Zaman:</strong> <span id="turn-time">—</span>
            </p>
            <p style="margin-bottom: 0.5rem;">
              <strong>Sonuç:</strong> <span id="turn-result">—</span>
            </p>
            <p><strong>Açıklama:</strong> <span id="turn-message">—</span></p>
          </div>
        </div>

        <div class="card">
          <div class="section-title">Son Sistem Kayıtları</div>
          <div id="log-records" class="log-box">
            <div class="log-item">Kayıt bekleniyor...</div>
          </div>
        </div>
      </section>
    </main>

    <footer>
      CrytoBot Localhost Pano · Salt-okunur denetim · Host: 127.0.0.1
    </footer>
  </div>

  <script>
    (function() {
      let countdown = 5;

      function formatNumber(num, decimals = 2) {
        if (num === null || num === undefined || isNaN(num)) return "—";
        return Number(num).toLocaleString("tr-TR", {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals
        });
      }

      function updateDashboard(data) {
        const banner = document.getElementById("error-banner");
        if (data.error) {
          banner.textContent = data.error;
          banner.style.display = "block";
        } else {
          banner.style.display = "none";
        }

        // Başlık Rozetleri
        const procBadge = document.getElementById("badge-process");
        if (data.is_running) {
          procBadge.textContent = "Çalışıyor";
          procBadge.className = "badge badge-running";
        } else {
          procBadge.textContent = "Durdu";
          procBadge.className = "badge badge-stopped";
        }

        const modeBadge = document.getElementById("badge-mode");
        modeBadge.textContent = data.mode || "paper";

        const haltBadge = document.getElementById("badge-halt");
        if (data.kill_switch) {
          haltBadge.textContent = "Kill Switch Devrede";
          haltBadge.className = "badge badge-halt-kill";
        } else if (data.halted) {
          haltBadge.textContent = "Drawdown Durdurması";
          haltBadge.className = "badge badge-halt-drawdown";
        } else {
          haltBadge.textContent = "Normal";
          haltBadge.className = "badge badge-halt-none";
        }

        // Metrik Kartları
        if (data.equity !== undefined) {
          document.getElementById("metric-equity").textContent = formatNumber(data.equity);
        }
        if (data.free_balance !== undefined) {
          document.getElementById("metric-free").textContent = formatNumber(data.free_balance);
        }
        if (data.peak_equity !== undefined) {
          document.getElementById("metric-peak").textContent = formatNumber(data.peak_equity);
        }

        // PnL
        const pnlEl = document.getElementById("metric-pnl");
        const pnlPctEl = document.getElementById("metric-pnl-pct");
        if (data.daily_pnl !== undefined) {
          const pnl = Number(data.daily_pnl);
          const pnlPct = Number(data.daily_pnl_pct || 0);
          pnlEl.textContent = (pnl > 0 ? "+" : "") + formatNumber(pnl) + " USDT";
          pnlPctEl.textContent = (pnlPct > 0 ? "+" : "") + formatNumber(pnlPct, 2) + "%";
          if (pnl > 0) {
            pnlEl.className = "card-value val-positive";
          } else if (pnl < 0) {
            pnlEl.className = "card-value val-negative";
          } else {
            pnlEl.className = "card-value";
          }
        }

        // Drawdown
        if (data.drawdown_pct !== undefined) {
          const dd = Math.max(0, Number(data.drawdown_pct));
          document.getElementById("metric-drawdown").textContent = formatNumber(dd, 2) + "%";
          const bar = document.getElementById("metric-drawdown-bar");
          bar.style.width = Math.min(100, dd) + "%";
          if (dd > 5) {
            bar.style.backgroundColor = "var(--red)";
          } else {
            bar.style.backgroundColor = "var(--amber)";
          }
        }

        // Pozisyonlar Tablosu
        const posCountEl = document.getElementById("pos-count");
        const tbody = document.getElementById("positions-body");
        const positions = Array.isArray(data.positions) ? data.positions : [];
        posCountEl.textContent = positions.length;

        if (positions.length === 0) {
          tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Açık pozisyon yok</td></tr>';
        } else {
          tbody.innerHTML = positions.map(pos => {
            const pnl = pos.unrealized_pnl !== undefined ? Number(pos.unrealized_pnl) : 0;
            const pnlClass = pnl > 0 ? "val-positive" : (pnl < 0 ? "val-negative" : "");
            const pnlText = (pnl > 0 ? "+" : "") + formatNumber(pnl) + " USDT";
            return `<tr>
              <td><strong>${pos.pair || "—"}</strong></td>
              <td>${pos.direction || "ALIM"}</td>
              <td>${formatNumber(pos.amount, 4)}</td>
              <td>${formatNumber(pos.entry_price, 4)}</td>
              <td>${formatNumber(pos.current_price, 4)}</td>
              <td>${formatNumber(pos.stop_loss, 4)}</td>
              <td>${formatNumber(pos.take_profit, 4)}</td>
              <td class="${pnlClass}"><strong>${pnlText}</strong></td>
            </tr>`;
          }).join("");
        }

        // Son Tur
        if (data.last_turn) {
          document.getElementById("turn-time").textContent = data.last_turn.time || "—";
          document.getElementById("turn-result").textContent = data.last_turn.status || "—";
          document.getElementById("turn-message").textContent = data.last_turn.message || "—";
        }

        // Son Kayıtlar
        const logsBox = document.getElementById("log-records");
        const logs = Array.isArray(data.logs) ? data.logs : [];
        if (logs.length > 0) {
          logsBox.innerHTML = logs.map(l => `<div class="log-item">${l}</div>`).join("");
        }
      }

      function fetchStatus() {
        fetch("/api/status")
          .then(res => {
            if (!res.ok) {
              return res.json().catch(() => ({ error: "HTTP " + res.status }));
            }
            return res.json();
          })
          .then(data => {
            updateDashboard(data);
          })
          .catch(err => {
            updateDashboard({ error: "Sunucuya bağlanılamadı: " + err.message });
          });
      }

      function resetCountdown() {
        countdown = 5;
        const text = document.getElementById("countdown-text");
        text.textContent = "Yenileniyor: " + countdown + "s";
      }

      function tick() {
        countdown--;
        if (countdown <= 0) {
          fetchStatus();
          resetCountdown();
        } else {
          document.getElementById("countdown-text").textContent = "Yenileniyor: " + countdown + "s";
        }
      }

      document.getElementById("btn-refresh").addEventListener("click", function() {
        fetchStatus();
        resetCountdown();
      });

      // İlk yükleme
      fetchStatus();
      setInterval(tick, 1000);
    })();
  </script>
</body>
</html>
"""


def render_dashboard_html() -> str:
    """Tek sayfa HTML arayüzünü döndürür."""
    return HTML_TEMPLATE
