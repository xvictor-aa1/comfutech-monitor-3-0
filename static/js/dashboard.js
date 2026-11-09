/**
 * dashboard.js — Lógica del dashboard principal.
 *
 * Usado por: core/dashboard.html
 *
 * Depende de:
 *   - LiveCards (escapeHtml, signalStrokeColor)
 *   - Toasts    (success, warning, danger, alert)
 *
 * API pública:
 *   Dashboard.init(config)
 *
 * config:
 *   {
 *     deviceIds: number[],           // IDs de los equipos a mostrar
 *     urls: {
 *       live:      string,           // endpoint de devices_live
 *       sparkline: string,           // endpoint de dashboard_sparkline
 *       alerts:    string,           // endpoint de recent_alerts_api
 *       discovery: string,           // endpoint de discover_all
 *     },
 *     refreshMs:       number,       // default 15000
 *     alertsPollMs:    number,       // default 30000
 *     sparklineMinutes: number,      // default 10
 *     alertListUrl:    string,       // default '/alertas/'
 *     ruleUrlTemplate: string,       // default '/alertas/?rule_id={id}'
 *   }
 *
 * Carga:
 *   <script src="{% static 'js/live-cards.js' %}"></script>
 *   <script src="{% static 'js/toasts.js' %}"></script>
 *   <script src="{% static 'js/dashboard.js' %}"></script>
 */

window.Dashboard = (function () {
    'use strict';

    // ============================================================
    // ESTADO INTERNO
    // ============================================================
    let _config = {
        deviceIds: [],
        urls: {},
        refreshMs: 15000,
        alertsPollMs: 30000,
        sparklineMinutes: 10,
        alertListUrl: '/alertas/',
        ruleUrlTemplate: '/alertas/?rule_id={id}',
    };

    let _dashTimer = null;
    let _alertsTimer = null;
    let _lastAlertTimestamp = null;
    let _shownAlertIds = new Set();

    // ============================================================
    // HELPERS
    // ============================================================
    const escapeHtmlJs = (typeof LiveCards !== 'undefined')
        ? LiveCards.escapeHtml
        : function (s) {
            if (s === null || s === undefined) return '';
            return String(s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        };

    const signalStrokeColor = (typeof LiveCards !== 'undefined')
        ? LiveCards.signalStrokeColor
        : function (s) {
            if (s < -80) return '#dc3545';
            if (s < -70) return '#e67e00';
            return '#198754';
        };

    /**
     * Formato COMPACTO de bps (ej: "1.5M") — distinto del de LiveCards
     * porque la card del dashboard tiene menos espacio.
     */
    function formatBps(v) {
        if (v === null || v === undefined) return '—';
        if (v >= 1e9) return (v / 1e9).toFixed(1) + 'G';
        if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
        if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
        return v.toFixed(0);
    }

    function roleBadge(role) {
        const classes = {
            'core':         'badge-core',
            'distribution': 'badge-distribution',
            'access':       'badge-access',
            'cpe':          'badge-cpe',
        };
        const labels = {
            'core':         'Core',
            'distribution': 'Distrib.',
            'access':       'Acceso',
            'cpe':          'CPE',
        };
        return `<span class="badge badge-role ${classes[role] || 'badge-cpe'}"
                      style="font-size: 0.62rem;">
                    ${labels[role] || role}
                </span>`;
    }

    function signalColorClass(signal) {
        if (signal === null || signal === undefined) return 'bg-secondary';
        if (signal < -80) return 'bg-danger';
        if (signal < -70) return 'bg-warning';
        if (signal < -50) return 'bg-success';
        return 'bg-info';
    }

    function signalToPercent(signal) {
        if (signal === null || signal === undefined) return 0;
        const pct = ((signal + 100) / 80) * 100;
        return Math.max(0, Math.min(100, pct));
    }

    function utilColorClass(util) {
        if (util === null || util === undefined) return 'bg-secondary';
        if (util > 85) return 'bg-danger';
        if (util > 70) return 'bg-warning';
        if (util > 40) return 'bg-info';
        return 'bg-success';
    }

    /**
     * Sparkline COMPACTO (28px de alto) — específico del dashboard.
     * Los bloques de monitor_live y device_detail usan el de 36px
     * que renderiza LiveCards.renderAllBlocks internamente.
     */
    function renderSparklineSvg(points, color) {
        if (!points || points.length < 2) {
            return '<div class="text-muted small text-center" style="height:28px;line-height:28px;"><i class="bi bi-dash"></i></div>';
        }
        const values = points.map(p => p.v).filter(v => v !== null && !isNaN(v));
        if (values.length < 2) return '';

        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min || 1;

        const W = 100;
        const H = 28;
        const stepX = W / (values.length - 1);

        const points_str = values.map((v, i) => {
            const x = i * stepX;
            const y = H - ((v - min) / range) * (H - 4) - 2;
            return `${x.toFixed(2)},${y.toFixed(2)}`;
        }).join(' ');

        const area_path = `M0,${H} L${points_str.replace(/ /g, ' L')} L${W},${H} Z`;
        const stroke = color || '#0d6efd';

        return `
            <svg class="sparkline-svg" viewBox="0 0 ${W} ${H}"
                 preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <path d="${area_path}" fill="${stroke}" opacity="0.15"></path>
                <polyline points="${points_str}"
                          fill="none" stroke="${stroke}" stroke-width="1.2"
                          stroke-linejoin="round" stroke-linecap="round"></polyline>
            </svg>
        `;
    }

    // ============================================================
    // SPARKLINE
    // ============================================================
    const _sparklineCache = {};

    async function loadSparkline(deviceId, metric) {
        const key = `${deviceId}:${metric}`;
        try {
            const url = `${_config.urls.sparkline}?device_id=${deviceId}&metric=${metric}&minutes=${_config.sparklineMinutes}`;
            const response = await fetch(url, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' },
            });
            if (!response.ok) return;
            const data = await response.json();
            _sparklineCache[key] = data.points || [];

            const el = document.querySelector(
                `.sparkline-slot[data-device-id="${deviceId}"][data-metric="${metric}"]`
            );
            if (el) {
                const color = metric === 'signal'
                    ? (data.points.length
                        ? signalStrokeColor(data.points[data.points.length - 1].v)
                        : '#0d6efd')
                    : '#0d6efd';
                el.innerHTML = renderSparklineSvg(data.points, color);
            }
        } catch (e) {
            console.warn('Error cargando sparkline:', e);
        }
    }

    // ============================================================
    // RENDER DE CARD COMPACTA
    // ============================================================
    function renderDeviceCard(device) {
        const icmp = device.icmp || {};
        const isWireless = device.is_wireless_link;

        let statusClass = 'unknown';
        let statusText = 'Sin datos';
        let statusIcon = 'question-circle';
        let icmpDetail = '';

        if (icmp.alive === null || icmp.alive === undefined) {
            statusClass = 'unknown';
        } else if (icmp.alive) {
            statusClass = 'alive';
            statusText = 'Vivo';
            statusIcon = 'check-circle-fill';
            if (icmp.rtt !== null && icmp.rtt !== undefined) {
                icmpDetail = ` · ${icmp.rtt.toFixed(1)} ms`;
            }
        } else {
            statusClass = 'down';
            statusText = 'Caído';
            statusIcon = 'x-circle-fill';
        }

        const cardCls = statusClass === 'down' ? 'device-down' : '';

        const wirelessBadge = isWireless ? `
            <span class="badge bg-info text-dark ms-1"
                  style="font-size: 0.6rem;" title="Radioenlace">
                <i class="bi bi-broadcast-pin"></i>
            </span>
        ` : '';

        let metricsSection = '';

        if (isWireless) {
            const radio = device.radio;
            if (radio && radio.signal !== null && radio.signal !== undefined) {
                const sig = radio.signal;
                const sigPct = signalToPercent(sig);
                const sigColor = signalColorClass(sig);
                const tx = formatBps(radio.tx_rate);
                const rx = formatBps(radio.rx_rate);

                metricsSection = `
                    <div class="mt-2 pt-2 border-top">
                        <div class="d-flex justify-content-between align-items-center mb-1"
                             style="font-size: 0.72rem;">
                            <span class="text-muted">
                                <i class="bi bi-reception-4"></i> Señal
                            </span>
                            <strong class="${sig < -80 ? 'text-danger' : sig < -70 ? 'text-warning' : 'text-success'}">
                                ${sig.toFixed(0)} dBm
                            </strong>
                        </div>
                        <div class="progress radio-signal-bar mb-2">
                            <div class="progress-bar ${sigColor}"
                                 style="width: ${sigPct}%;"></div>
                        </div>
                        <div class="sparkline-slot"
                             data-device-id="${device.id}"
                             data-metric="signal">
                            <div class="text-center text-muted" style="height:28px;line-height:28px;font-size:0.7rem;">
                                <i class="bi bi-dash"></i>
                            </div>
                        </div>
                        <div class="d-flex justify-content-between mt-1"
                             style="font-size: 0.72rem;">
                            <span class="text-success">
                                <i class="bi bi-arrow-down-circle"></i> ${tx}
                            </span>
                            <span class="text-warning">
                                <i class="bi bi-arrow-up-circle"></i> ${rx}
                            </span>
                        </div>
                    </div>
                `;
            } else {
                metricsSection = `
                    <div class="mt-2 pt-2 border-top text-muted fst-italic"
                         style="font-size: 0.72rem;">
                        <i class="bi bi-broadcast-pin"></i> Sin datos de RF
                    </div>
                `;
            }
        } else {
            const wan = device.dashboard_traffic;
            if (wan) {
                const util = wan.utilization;
                const utilPct = util !== null && util !== undefined
                    ? Math.min(util, 100) : 0;
                const utilColor = utilColorClass(util);

                metricsSection = `
                    <div class="mt-2 pt-2 border-top">
                        <div class="d-flex justify-content-between align-items-center mb-1"
                             style="font-size: 0.72rem;">
                            <span class="text-muted text-truncate"
                                  style="max-width: 70%;">
                                <i class="bi bi-ethernet"></i>
                                ${escapeHtmlJs(wan.interface || 'WAN')}
                                ${wan.alias ? `<small>(${escapeHtmlJs(wan.alias)})</small>` : ''}
                            </span>
                            <strong class="text-muted">
                                ${util !== null && util !== undefined ? util.toFixed(1) + '%' : '—'}
                            </strong>
                        </div>
                        <div class="progress radio-signal-bar mb-2">
                            <div class="progress-bar ${utilColor}"
                                 style="width: ${utilPct}%;"></div>
                        </div>
                        <div class="sparkline-slot"
                             data-device-id="${device.id}"
                             data-metric="traffic_in">
                            <div class="text-center text-muted" style="height:28px;line-height:28px;font-size:0.7rem;">
                                <i class="bi bi-dash"></i>
                            </div>
                        </div>
                        <div class="d-flex justify-content-between mt-1"
                             style="font-size: 0.72rem;">
                            <span class="text-success">
                                <i class="bi bi-arrow-down-circle"></i>
                                ${formatBps(wan.in_bps)}
                            </span>
                            <span class="text-warning">
                                <i class="bi bi-arrow-up-circle"></i>
                                ${formatBps(wan.out_bps)}
                            </span>
                        </div>
                    </div>
                `;
            } else {
                metricsSection = `
                    <div class="mt-2 pt-2 border-top text-muted fst-italic"
                         style="font-size: 0.72rem;">
                        <i class="bi bi-ethernet"></i> Sin datos de tráfico
                    </div>
                `;
            }
        }

        const detailUrl = `/equipos/${device.id}/`;
        const interfacesUrl = `/equipos/${device.id}/interfaces/`;
        const canManageInterfaces = device.has_interfaces_support || device.is_wireless_link;

        return `
            <div class="col-lg-4 col-md-6">
                <div class="card h-100 dashboard-device-card ${cardCls}"
                     data-device-id="${device.id}">
                    <div class="card-body p-3 d-flex flex-column">

                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <div class="flex-grow-1" style="min-width: 0;">
                                <div class="d-flex align-items-center gap-1">
                                    <span class="status-dot ${statusClass}"
                                          title="${statusText}"></span>
                                    <a href="${detailUrl}"
                                       class="text-decoration-none text-truncate device-name"
                                       title="${escapeHtmlJs(device.name)}">
                                        ${escapeHtmlJs(device.name)}
                                    </a>
                                    ${wirelessBadge}
                                </div>
                                <small class="text-muted d-block text-truncate"
                                       style="font-size: 0.7rem;">
                                    <code>${escapeHtmlJs(device.ip)}</code>
                                </small>
                            </div>
                            <div class="ms-1">
                                ${roleBadge(device.role)}
                            </div>
                        </div>

                        <div class="d-flex align-items-center gap-1 mt-1"
                             style="font-size: 0.72rem;">
                            <i class="bi bi-${statusIcon}
                                ${statusClass === 'alive' ? 'text-success'
                                  : statusClass === 'down' ? 'text-danger'
                                  : 'text-muted'}"></i>
                            <span class="${statusClass === 'alive' ? 'text-success'
                                  : statusClass === 'down' ? 'text-danger'
                                  : 'text-muted'}">
                                ${statusText}
                            </span>
                            ${icmpDetail ? `<span class="text-muted">${icmpDetail}</span>` : ''}
                        </div>

                        <div class="flex-grow-1">
                            ${metricsSection}
                        </div>

                        <div class="d-flex justify-content-between align-items-center mt-2 pt-2 border-top">
                            <a href="${detailUrl}"
                               class="btn btn-xs btn-outline-primary"
                               title="Ver detalle del equipo">
                                <i class="bi bi-info-circle"></i> Detalle
                            </a>
                            ${canManageInterfaces ? `
                            <a href="${interfacesUrl}"
                               class="btn btn-xs btn-outline-info"
                               title="${device.is_wireless_link ? 'Clientes AP' : 'Interfaces'}">
                                <i class="bi bi-${device.is_wireless_link ? 'broadcast-pin' : 'ethernet'}"></i>
                            </a>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    // ============================================================
    // CARGA DE DATOS
    // ============================================================
    async function loadDevices() {
        const container = document.getElementById('devices-container');
        if (!container) return;
        if (!_config.deviceIds || _config.deviceIds.length === 0) return;

        try {
            const response = await fetch(_config.urls.live, {
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            if (!response.ok) throw new Error('HTTP ' + response.status);

            const data = await response.json();
            const devicesMap = {};
            (data.devices || []).forEach(d => {
                if (_config.deviceIds.includes(d.id)) devicesMap[d.id] = d;
            });

            const ordered = _config.deviceIds
                .map(id => devicesMap[id])
                .filter(Boolean);

            if (ordered.length === 0) {
                container.innerHTML = `
                    <div class="col-12">
                        <div class="card">
                            <div class="card-body text-center text-muted py-5">
                                <i class="bi bi-inbox" style="font-size: 3rem;"></i>
                                <p class="mt-3 mb-0">
                                    Los equipos no responden al endpoint de monitoreo.
                                </p>
                            </div>
                        </div>
                    </div>
                `;
                return;
            }

            container.innerHTML = ordered.map(renderDeviceCard).join('');

            // Cargar sparklines en paralelo.
            ordered.forEach(d => {
                const metric = d.is_wireless_link ? 'signal' : 'traffic_in';
                loadSparkline(d.id, metric);
            });

            const ts = new Date(data.timestamp);
            const el = document.getElementById('last-update');
            if (el) el.textContent = ts.toLocaleTimeString('es-VE');

        } catch (e) {
            console.error('Error cargando equipos:', e);
            const el = document.getElementById('last-update');
            if (el) el.textContent = 'error';
        }
    }

    // ============================================================
    // TOASTS DE ALERTAS
    // ============================================================
    async function pollNewAlerts() {
        try {
            let url = _config.urls.alerts;
            if (_lastAlertTimestamp) {
                url += `?since=${encodeURIComponent(_lastAlertTimestamp)}`;
            }
            const response = await fetch(url, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' },
            });
            if (!response.ok) return;

            const data = await response.json();
            _lastAlertTimestamp = data.timestamp;

            (data.alerts || []).forEach(alert => {
                if (_shownAlertIds.has(alert.id)) return;
                _shownAlertIds.add(alert.id);

                if (typeof Toasts !== 'undefined') {
                    Toasts.alert(alert, {
                        id: `toast-alert-${alert.id}`,
                        alertListUrl: _config.alertListUrl,
                        ruleUrlTemplate: _config.ruleUrlTemplate,
                    });
                }
            });

            const ids = Array.from(_shownAlertIds).slice(-100);
            _shownAlertIds = new Set(ids);
            try {
                localStorage.setItem('dash_shown_alerts', JSON.stringify(ids));
            } catch (e) {}

        } catch (e) {
            console.warn('Error polling alertas:', e);
        }
    }

    // ============================================================
    // DISCOVERY
    // ============================================================
    async function runDashboardDiscovery() {
        const btn = document.getElementById('btn-confirm-discovery');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Ejecutando...';
        }

        try {
            const csrfToken = getCookie('csrftoken');
            const response = await fetch(_config.urls.discovery, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json',
                },
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();

            const modal = bootstrap.Modal.getInstance(document.getElementById('discoveryModal'));
            if (modal) modal.hide();

            const successCount = data.success_count || 0;
            const total = data.total || 0;
            const message = `${successCount}/${total} equipos procesados exitosamente.`;

            if (typeof Toasts !== 'undefined') {
                if (successCount === total) {
                    Toasts.success(message, { title: 'Discovery completado' });
                } else {
                    Toasts.warning(message, { title: 'Discovery con advertencias' });
                }
            } else {
                alert(`Discovery completado: ${message}`);
            }

            loadDevices();

        } catch (e) {
            console.error('Error en discovery:', e);
            if (typeof Toasts !== 'undefined') {
                Toasts.danger(e.message, { title: 'Error en Discovery' });
            } else {
                alert(`Error ejecutando Discovery: ${e.message}`);
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-fill"></i> Ejecutar ahora';
            }
        }
    }

    // ============================================================
    // AUTO-REFRESH
    // ============================================================
    function startAutoRefresh() {
        stopAutoRefresh();
        _dashTimer = setInterval(loadDevices, _config.refreshMs);
    }

    function stopAutoRefresh() {
        if (_dashTimer) {
            clearInterval(_dashTimer);
            _dashTimer = null;
        }
    }

    // ============================================================
    // INIT
    // ============================================================
    function init(config) {
        config = config || {};

        // Merge config (shallow para urls, directo para el resto).
        Object.keys(config).forEach(k => {
            if (k === 'urls') {
                _config.urls = Object.assign({}, _config.urls, config.urls || {});
            } else {
                _config[k] = config[k];
            }
        });

        // Restaurar alertas ya mostradas.
        try {
            const stored = localStorage.getItem('dash_shown_alerts');
            if (stored) {
                const ids = JSON.parse(stored);
                if (Array.isArray(ids)) _shownAlertIds = new Set(ids);
            }
        } catch (e) {}

        // Exponer la función de discovery al window (la usa el modal inline).
        window.runDashboardDiscovery = runDashboardDiscovery;

        // Carga inicial.
        if (_config.deviceIds && _config.deviceIds.length > 0) {
            loadDevices();
        }

        // Polling de alertas (independiente del de devices).
        _lastAlertTimestamp = new Date().toISOString();
        pollNewAlerts();
        _alertsTimer = setInterval(pollNewAlerts, _config.alertsPollMs);

        // Toggle de auto-refresh.
        const toggle = document.getElementById('auto-refresh');
        if (toggle) {
            toggle.addEventListener('change', () => {
                if (toggle.checked) startAutoRefresh();
                else stopAutoRefresh();
            });
            if (toggle.checked && _config.deviceIds.length > 0) {
                startAutoRefresh();
            }
        }

        // Pausar/reanudar al cambiar de pestaña.
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                stopAutoRefresh();
                if (_alertsTimer) {
                    clearInterval(_alertsTimer);
                    _alertsTimer = null;
                }
            } else {
                const toggleEl = document.getElementById('auto-refresh');
                if (toggleEl && toggleEl.checked && _config.deviceIds.length > 0) {
                    startAutoRefresh();
                    loadDevices();
                }
                pollNewAlerts();
                if (!_alertsTimer) {
                    _alertsTimer = setInterval(pollNewAlerts, _config.alertsPollMs);
                }
            }
        });
    }

    return { init, runDiscovery: runDashboardDiscovery };
})();