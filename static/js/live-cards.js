/**
 * live-cards.js — Renderizado compartido de cards de monitoreo en vivo.
 *
 * Usado por:
 *   - monitor_live.html (múltiples cards)
 *   - device_detail.html (bloques de un solo equipo)
 *
 * No usado por:
 *   - device_interfaces.html (tiene su propio renderizado de tablas AP)
 *   - dashboard.html (solo consume escapeHtml y signalStrokeColor)
 *
 * API pública:
 *   LiveCards.configure({sparklineUrl, sparklineMinutes, interfacesUrlTemplate})
 *   LiveCards.formatBps(v), LiveCards.formatUptime(s), LiveCards.relativeTime(iso)
 *   LiveCards.escapeHtml(s), LiveCards.utilColor(p), LiveCards.signalColor(s)
 *   LiveCards.signalStrokeColor(s)
 *   LiveCards.renderAllBlocks(device)   → devuelve el HTML de todos los bloques
 *   LiveCards.observeSparklines()       → llamar tras inyectar HTML
 *   LiveCards.refreshVisibleSparklines()→ recarga sparklines visibles (30s)
 *   LiveCards.resetSparklineCache()
 *   LiveCards.initViewMode(callback)    → engancha los radios y persiste en localStorage
 *   LiveCards.setViewMode(mode), LiveCards.getViewMode()
 *
 * Límites de visualización (para no saturar las cards):
 *   - IF-MIB (tráfico): máximo 5 interfaces. Si hay más, aparece un botón
 *     "Ver todas" que redirige a la página de interfaces del equipo.
 *   - Clientes AP: máximo 5 clientes (ordenados online primero). Si hay
 *     más, aparece un botón "Ver todos" que redirige a la página de
 *     interfaces del equipo.
 *
 * Los límites solo aplican al modo ESTÁTICO del bloque de tráfico
 * (el modo gráfico muestra solo WAN, así que no hay nada que limitar).
 * Los clientes AP no tienen modo gráfico: siempre se limitan a 5.
 */
window.LiveCards = (function () {
    'use strict';

    // ============================================================
    // CONFIGURACIÓN
    // ============================================================
    let _sparklineUrl = '';
    let _sparklineMinutes = 10;
    let _interfacesUrlTemplate = '';  // ej: "/equipos/{id}/interfaces/"
    const _sparklineCacheMs = 25000;

    // Límites de visualización
    const MAX_TRAFFIC_ROWS = 5;
    const MAX_AP_CLIENTS = 5;

    // ============================================================
    // ESTADO INTERNO
    // ============================================================
    let _sparklineObserver = null;
    const _sparklineCache = new Map();
    let _currentViewMode = 'static';
    let _onViewModeChange = null;

    // ============================================================
    // HELPERS
    // ============================================================
    function formatBps(v) {
        if (v === null || v === undefined) return '—';
        if (v >= 1e9) return (v / 1e9).toFixed(2) + ' Gbps';
        if (v >= 1e6) return (v / 1e6).toFixed(2) + ' Mbps';
        if (v >= 1e3) return (v / 1e3).toFixed(2) + ' Kbps';
        return v.toFixed(0) + ' bps';
    }

    function formatUptime(seconds) {
        if (seconds === null || seconds === undefined) return '—';
        const d = Math.floor(seconds / 86400);
        const h = Math.floor((seconds % 86400) / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        if (d > 0) return `${d}d ${h}h`;
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    }

    function relativeTime(isoTs) {
        if (!isoTs) return '—';
        const d = new Date(isoTs);
        if (isNaN(d.getTime())) return '—';
        const diff = Math.floor((Date.now() - d.getTime()) / 1000);
        if (diff < 5) return 'ahora';
        if (diff < 60) return `hace ${diff}s`;
        if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`;
        if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`;
        return `hace ${Math.floor(diff / 86400)}d`;
    }

    function escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function utilColor(pct) {
        if (pct === null || pct === undefined) return 'bg-secondary';
        if (pct > 85) return 'bg-danger';
        if (pct > 70) return 'bg-warning';
        if (pct > 40) return 'bg-info';
        return 'bg-success';
    }

    function signalColor(s) {
        if (s === null || s === undefined) return '';
        if (s < -80) return 'text-danger';
        if (s < -70) return 'text-warning';
        return 'text-success';
    }

    function signalStrokeColor(s) {
        if (s === null || s === undefined) return '#0d6efd';
        if (s < -80) return '#dc3545';
        if (s < -70) return '#e67e00';
        return '#198754';
    }

    /**
     * Resuelve la URL de la página de interfaces de un equipo.
     *
     * Usa la plantilla configurada en `configure()` (con placeholder `{id}`).
     * Si no hay plantilla, devuelve null (y el botón "Ver todas" no se muestra).
     *
     * @param {number} deviceId
     * @returns {string|null}
     */
    function _deviceInterfacesUrl(deviceId) {
        if (!_interfacesUrlTemplate || !deviceId) return null;
        return _interfacesUrlTemplate.replace('{id}', deviceId);
    }

    // ============================================================
    // SPARKLINES
    // ============================================================
    function renderSparklineSvg(points, color) {
        if (!points || points.length < 2) {
            return '<div class="text-muted small text-center" style="height:36px;line-height:36px;"><i class="bi bi-dash"></i></div>';
        }
        const values = points.map(p => p.v).filter(v => v !== null && !isNaN(v));
        if (values.length < 2) return '';

        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min || 1;
        const W = 100, H = 36, pad = 2;
        const stepX = W / (values.length - 1);

        const pts = values.map((v, i) => {
            const x = i * stepX;
            const y = H - ((v - min) / range) * (H - pad * 2) - pad;
            return `${x.toFixed(2)},${y.toFixed(2)}`;
        }).join(' ');

        const area = `M0,${H} L${pts.replace(/ /g, ' L')} L${W},${H} Z`;
        const stroke = color || '#0d6efd';
        return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
                     xmlns="http://www.w3.org/2000/svg">
                    <path d="${area}" fill="${stroke}" opacity="0.15"></path>
                    <polyline points="${pts}" fill="none" stroke="${stroke}"
                              stroke-width="1.4" stroke-linejoin="round"
                              stroke-linecap="round"></polyline>
                </svg>`;
    }

    function sparklineSlotHtml(deviceId, metric, color) {
        return `<div class="sparkline-slot"
                     data-device-id="${deviceId}"
                     data-metric="${metric}"
                     data-color="${color || '#0d6efd'}">
                    <div class="sparkline-loading"></div>
                </div>`;
    }

    async function loadSparklineForSlot(slot) {
        const deviceId = parseInt(slot.dataset.deviceId, 10);
        const metric = slot.dataset.metric;
        const color = slot.dataset.color || '#0d6efd';
        if (!deviceId || !metric || !_sparklineUrl) return;

        const key = `${deviceId}:${metric}`;
        const cached = _sparklineCache.get(key);
        const now = Date.now();

        if (cached && (now - cached.ts) < _sparklineCacheMs) {
            slot.innerHTML = renderSparklineSvg(cached.points, color);
            return;
        }

        try {
            const url = `${_sparklineUrl}?device_id=${deviceId}&metric=${metric}&minutes=${_sparklineMinutes}`;
            const r = await fetch(url, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' },
            });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            const points = data.points || [];
            _sparklineCache.set(key, { points, ts: now });

            let stroke = color;
            if (metric === 'signal' && points.length > 0) {
                stroke = signalStrokeColor(points[points.length - 1].v);
            }
            slot.innerHTML = renderSparklineSvg(points, stroke);
        } catch (e) {
            console.warn(`Sparkline error (${metric}):`, e);
            slot.innerHTML = '<div class="text-muted small text-center" style="height:36px;line-height:36px;"><i class="bi bi-exclamation-triangle"></i></div>';
        }
    }

    function observeSparklines() {
        if (!('IntersectionObserver' in window)) {
            document.querySelectorAll('.sparkline-slot').forEach(loadSparklineForSlot);
            return;
        }
        if (_sparklineObserver) _sparklineObserver.disconnect();
        _sparklineObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !entry.target.dataset.loaded) {
                    entry.target.dataset.loaded = '1';
                    loadSparklineForSlot(entry.target);
                }
            });
        }, { rootMargin: '100px', threshold: 0.01 });
        document.querySelectorAll('.sparkline-slot:not([data-loaded])').forEach(s => {
            _sparklineObserver.observe(s);
        });
    }

    function refreshVisibleSparklines() {
        if (_currentViewMode !== 'chart') return;
        _sparklineCache.clear();
        document.querySelectorAll('.sparkline-slot').forEach(slot => {
            const rect = slot.getBoundingClientRect();
            if (rect.top < window.innerHeight && rect.bottom > 0) {
                slot.dataset.loaded = '';
                loadSparklineForSlot(slot);
            }
        });
    }

    // ============================================================
    // BLOQUES
    // ============================================================
    function renderWirelessBlock(wireless) {
        if (!wireless) return '';
        const u = (wireless.utilization_pct !== null && wireless.utilization_pct !== undefined)
            ? wireless.utilization_pct : null;
        const utilPct = u !== null ? u.toFixed(1) : '—';
        const bar = utilColor(u);
        const w = u !== null ? Math.min(u, 100) : 0;

        return `
            <div class="live-block">
                <div class="live-block-header">
                    <span><i class="bi bi-broadcast-pin text-info"></i> Radioenlace</span>
                    <span class="live-block-meta">
                        ${escapeHtml(wireless.interface || '—')}
                        ${wireless.alias ? '· ' + escapeHtml(wireless.alias) : ''}
                    </span>
                </div>
                <div class="row g-2 small mb-2">
                    <div class="col-4"><div class="text-muted">Capacidad</div><div class="fw-bold">${formatBps(wireless.capacity_bps)}</div></div>
                    <div class="col-4"><div class="text-muted">RX</div><div class="fw-bold text-success">↓ ${formatBps(wireless.in_bps)}</div></div>
                    <div class="col-4"><div class="text-muted">TX</div><div class="fw-bold text-warning">↑ ${formatBps(wireless.out_bps)}</div></div>
                </div>
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <small class="text-muted">Utilización</small>
                    <small class="fw-bold">${utilPct}%</small>
                </div>
                <div class="progress" style="height:8px;">
                    <div class="progress-bar ${bar}" style="width:${w}%;"></div>
                </div>
            </div>`;
    }

    function renderRadioBlock(device, chartMode) {
        if (!device.has_radio_metrics) return '';
        const radio = device.radio;
        if (!radio) {
            return `<div class="live-block">
                <div class="live-block-header"><span><i class="bi bi-broadcast-pin text-info"></i> Radiofrecuencia</span></div>
                <div class="text-muted small fst-italic">Sin datos recientes</div></div>`;
        }
        const freq = radio.freq != null ? radio.freq.toFixed(0) + ' MHz' : '—';
        const txp  = radio.txpower != null ? radio.txpower.toFixed(0) + ' dBm' : '—';
        const sig  = radio.signal != null ? radio.signal.toFixed(0) + ' dBm' : '—';
        const noi  = radio.noise != null ? radio.noise.toFixed(0) + ' dBm' : '—';
        const ccq  = radio.ccq != null ? radio.ccq.toFixed(0) + '%' : '—';
        const txr  = formatBps(radio.tx_rate);
        const rxr  = formatBps(radio.rx_rate);
        const chw  = radio.chan_width != null ? radio.chan_width.toFixed(0) + ' MHz' : '—';
        const sigC = signalColor(radio.signal);
        const noiC = radio.noise > -80 ? 'text-danger' : radio.noise > -90 ? 'text-warning' : '';
        const ccqC = radio.ccq < 50 ? 'text-danger' : radio.ccq < 80 ? 'text-warning' : 'text-success';

        if (chartMode) {
            return `<div class="live-block">
                <div class="live-block-header">
                    <span><i class="bi bi-broadcast-pin text-info"></i> Radiofrecuencia</span>
                    <span class="live-block-meta">${relativeTime(radio.ts)}</span>
                </div>
                <div class="live-metric-row">
                    <span class="live-metric-label">Signal</span>
                    <div class="live-metric-chart">${sparklineSlotHtml(device.id, 'signal', signalStrokeColor(radio.signal))}</div>
                    <span class="live-metric-value ${sigC}">${sig}</span>
                </div>
                <div class="row g-2 small mt-2">
                    <div class="col-4"><div class="text-muted" style="font-size:0.7rem;">Freq</div><div class="fw-bold">${freq}</div></div>
                    <div class="col-4"><div class="text-muted" style="font-size:0.7rem;">Noise</div><div class="fw-bold ${noiC}">${noi}</div></div>
                    <div class="col-4"><div class="text-muted" style="font-size:0.7rem;">CCQ</div><div class="fw-bold ${ccqC}">${ccq}</div></div>
                    <div class="col-4"><div class="text-muted" style="font-size:0.7rem;">TX Rate</div><div class="fw-bold text-success">↓ ${txr}</div></div>
                    <div class="col-4"><div class="text-muted" style="font-size:0.7rem;">RX Rate</div><div class="fw-bold text-warning">↑ ${rxr}</div></div>
                    <div class="col-4"><div class="text-muted" style="font-size:0.7rem;">Canal</div><div class="fw-bold">${chw}</div></div>
                </div></div>`;
        }
        return `<div class="live-block">
            <div class="live-block-header">
                <span><i class="bi bi-broadcast-pin text-info"></i> Radiofrecuencia</span>
                <span class="live-block-meta">${relativeTime(radio.ts)}</span>
            </div>
            <div class="row g-2 small">
                <div class="col-4"><div class="text-muted">Frecuencia</div><div class="fw-bold">${freq}</div></div>
                <div class="col-4"><div class="text-muted">TX Power</div><div class="fw-bold">${txp}</div></div>
                <div class="col-4"><div class="text-muted">Ancho canal</div><div class="fw-bold">${chw}</div></div>
                <div class="col-4"><div class="text-muted">Signal</div><div class="fw-bold ${sigC}">${sig}</div></div>
                <div class="col-4"><div class="text-muted">Noise</div><div class="fw-bold ${noiC}">${noi}</div></div>
                <div class="col-4"><div class="text-muted">CCQ</div><div class="fw-bold ${ccqC}">${ccq}</div></div>
                <div class="col-4"><div class="text-muted">TX Rate</div><div class="fw-bold text-success">↓ ${txr}</div></div>
                <div class="col-4"><div class="text-muted">RX Rate</div><div class="fw-bold text-warning">↑ ${rxr}</div></div>
                <div class="col-4"><div class="text-muted">airMAX</div><div class="fw-bold">Q:${radio.airmax_quality ?? '—'} C:${radio.airmax_capacity ?? '—'}</div></div>
            </div></div>`;
    }

    function renderIcmpBlock(device, chartMode) {
        const icmp = device.icmp;
        if (!icmp) {
            return `<div class="live-block">
                <div class="live-block-header"><span><i class="bi bi-activity"></i> ICMP</span></div>
                <div class="text-muted small fst-italic">Sin datos recientes</div></div>`;
        }
        const aliveC = icmp.alive ? 'text-success' : 'text-danger';
        const aliveI = icmp.alive ? 'check-circle-fill' : 'x-circle-fill';
        const aliveT = icmp.alive ? 'Vivo' : 'Caído';
        const lossC = icmp.loss > 5 ? 'text-danger' : icmp.loss > 0 ? 'text-warning' : '';
        const rttV = icmp.rtt != null ? icmp.rtt.toFixed(1) + ' ms' : '—';
        const lossV = icmp.loss != null ? icmp.loss.toFixed(0) + '%' : '—';

        if (chartMode) {
            return `<div class="live-block">
                <div class="live-block-header">
                    <span><i class="bi bi-activity"></i> ICMP</span>
                    <span class="live-block-meta">${relativeTime(icmp.ts)}</span>
                </div>
                <div class="mb-1"><span class="${aliveC} fw-bold small"><i class="bi bi-${aliveI}"></i> ${aliveT}</span></div>
                <div class="live-metric-row">
                    <span class="live-metric-label">Latencia</span>
                    <div class="live-metric-chart">${sparklineSlotHtml(device.id, 'latency', '#0d6efd')}</div>
                    <span class="live-metric-value">${rttV}</span>
                </div>
                <div class="live-metric-row">
                    <span class="live-metric-label">Pérdida</span>
                    <div class="live-metric-chart"></div>
                    <span class="live-metric-value ${lossC}">${lossV}</span>
                </div></div>`;
        }
        return `<div class="live-block">
            <div class="live-block-header">
                <span><i class="bi bi-activity"></i> ICMP</span>
                <span class="live-block-meta">${relativeTime(icmp.ts)}</span>
            </div>
            <div class="row g-2 small">
                <div class="col-4"><div class="text-muted">Estado</div><div class="${aliveC} fw-bold"><i class="bi bi-${aliveI}"></i> ${aliveT}</div></div>
                <div class="col-4"><div class="text-muted">Latencia</div><div class="fw-bold">${rttV}</div></div>
                <div class="col-4"><div class="text-muted">Pérdida</div><div class="fw-bold ${lossC}">${lossV}</div></div>
            </div></div>`;
    }

    /**
     * Bloque de tráfico SNMP.
     *
     * En modo estático, si hay más de MAX_TRAFFIC_ROWS interfaces
     * monitoreadas, se muestran solo las primeras MAX_TRAFFIC_ROWS y
     * se añade un botón "Ver todas" que redirige a la página de
     * interfaces del equipo (solo si `interfacesUrlTemplate` está
     * configurado).
     *
     * En modo gráfico, solo se muestra la interfaz WAN (o la primera
     * disponible), por lo que no aplica el límite.
     */
    function renderTrafficBlock(device, chartMode) {
        if (!device.has_interfaces_support) return '';
        const traffic = device.traffic || [];

        if (!device.has_traffic) {
            return `<div class="live-block">
                <div class="live-block-header"><span><i class="bi bi-graph-up"></i> SNMP Tráfico</span></div>
                <div class="text-muted small fst-italic">Sin interfaces monitoreadas</div></div>`;
        }

        if (chartMode) {
            const wan = device.dashboard_traffic || (traffic.length ? traffic[0] : null);
            if (!wan) {
                return `<div class="live-block">
                    <div class="live-block-header"><span><i class="bi bi-graph-up"></i> SNMP Tráfico (WAN)</span></div>
                    <div class="text-muted small fst-italic">Sin datos WAN</div></div>`;
            }
            const util = wan.utilization;
            const utilPct = util != null ? util.toFixed(1) : '—';
            const utilC = util > 85 ? 'text-danger' : util > 70 ? 'text-warning' : '';
            return `<div class="live-block">
                <div class="live-block-header">
                    <span><i class="bi bi-graph-up"></i> SNMP Tráfico (WAN)</span>
                    <span class="live-block-meta">
                        ${escapeHtml(wan.interface || '—')}
                        ${wan.alias ? '· ' + escapeHtml(wan.alias) : ''}
                    </span>
                </div>
                <div class="live-metric-row">
                    <span class="live-metric-label text-success">↓ RX</span>
                    <div class="live-metric-chart">${sparklineSlotHtml(device.id, 'traffic_in', '#198754')}</div>
                    <span class="live-metric-value text-success">${formatBps(wan.in_bps)}</span>
                </div>
                <div class="live-metric-row">
                    <span class="live-metric-label text-warning">↑ TX</span>
                    <div class="live-metric-chart">${sparklineSlotHtml(device.id, 'traffic_out', '#e67e00')}</div>
                    <span class="live-metric-value text-warning">${formatBps(wan.out_bps)}</span>
                </div>
                <div class="d-flex justify-content-between align-items-center mt-1">
                    <small class="text-muted">Utilización</small>
                    <small class="fw-bold ${utilC}">${utilPct}%</small>
                </div>
                ${util != null ? `<div class="progress" style="height:6px;"><div class="progress-bar ${utilColor(util)}" style="width:${Math.min(util, 100)}%;"></div></div>` : ''}
            </div>`;
        }

        if (traffic.length === 0) {
            return `<div class="live-block">
                <div class="live-block-header"><span><i class="bi bi-graph-up"></i> SNMP Tráfico</span></div>
                <div class="text-muted small fst-italic">Sin datos recientes</div></div>`;
        }

        // ─── Modo estático: limitar a MAX_TRAFFIC_ROWS interfaces ───
        const totalTraffic = traffic.length;
        const visibleTraffic = traffic.slice(0, MAX_TRAFFIC_ROWS);
        const hasMore = totalTraffic > MAX_TRAFFIC_ROWS;
        const interfacesUrl = _deviceInterfacesUrl(device.id);

        const rows = visibleTraffic.map(t => `
            <tr>
                <td><code class="small">${escapeHtml(t.interface || '—')}</code></td>
                <td class="small text-muted">${escapeHtml(t.alias) || '—'}</td>
                <td class="text-end text-success small">↓ ${formatBps(t.in_bps)}</td>
                <td class="text-end text-warning small">↑ ${formatBps(t.out_bps)}</td>
                <td class="text-end small">${t.utilization != null ? t.utilization.toFixed(1) + '%' : '—'}</td>
            </tr>`).join('');

        const moreButton = (hasMore && interfacesUrl) ? `
            <div class="text-center mt-2">
                <a href="${interfacesUrl}" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-ethernet"></i>
                    Ver todas las ${totalTraffic} interfaces
                    <i class="bi bi-arrow-right"></i>
                </a>
            </div>
        ` : '';

        const metaLabel = hasMore
            ? `${visibleTraffic.length} de ${totalTraffic} interfaces`
            : `${totalTraffic} interfaz${totalTraffic !== 1 ? 'es' : ''}`;

        return `<div class="live-block">
            <div class="live-block-header">
                <span><i class="bi bi-graph-up"></i> SNMP Tráfico</span>
                <span class="live-block-meta">${metaLabel}</span>
            </div>
            <div class="table-responsive">
                <table class="table table-sm table-borderless mb-0">
                    <thead><tr class="small text-muted">
                        <th>Interfaz</th><th>Alias</th>
                        <th class="text-end">RX</th><th class="text-end">TX</th>
                        <th class="text-end">Uso</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            ${moreButton}
        </div>`;
    }

    function renderHealthBlock(device, chartMode) {
        if (!device.has_health_metrics) return '';
        const h = device.health;
        const avail = device.available_health_metrics || [];
        if (!h) {
            return `<div class="live-block">
                <div class="live-block-header"><span><i class="bi bi-heart-pulse"></i> Core Health</span></div>
                <div class="text-muted small fst-italic">Sin datos recientes</div></div>`;
        }
        if (chartMode) {
            const rows = [];
            if (avail.includes('cpu_pct')) {
                const c = h.cpu > 90 ? 'text-danger' : h.cpu > 75 ? 'text-warning' : '';
                const v = h.cpu != null ? h.cpu.toFixed(0) + '%' : '—';
                rows.push(`<div class="live-metric-row"><span class="live-metric-label">CPU</span><div class="live-metric-chart">${sparklineSlotHtml(device.id, 'cpu', '#0d6efd')}</div><span class="live-metric-value ${c}">${v}</span></div>`);
            }
            if (avail.includes('mem_pct')) {
                const c = h.mem > 92 ? 'text-danger' : h.mem > 80 ? 'text-warning' : '';
                const v = h.mem != null ? h.mem.toFixed(0) + '%' : '—';
                rows.push(`<div class="live-metric-row"><span class="live-metric-label">Mem</span><div class="live-metric-chart">${sparklineSlotHtml(device.id, 'mem', '#0dcaf0')}</div><span class="live-metric-value ${c}">${v}</span></div>`);
            }
            if (avail.includes('temp_c')) {
                const c = h.temp > 85 ? 'text-danger' : h.temp > 70 ? 'text-warning' : '';
                const v = h.temp != null ? h.temp.toFixed(0) + '°C' : '—';
                rows.push(`<div class="live-metric-row"><span class="live-metric-label">Temp</span><div class="live-metric-chart">${sparklineSlotHtml(device.id, 'temp', '#dc3545')}</div><span class="live-metric-value ${c}">${v}</span></div>`);
            }
            return `<div class="live-block">
                <div class="live-block-header">
                    <span><i class="bi bi-heart-pulse"></i> Core Health</span>
                    <span class="live-block-meta">${relativeTime(h.ts)}</span>
                </div>
                ${rows.join('')}
                <div class="live-metric-row mt-1">
                    <span class="live-metric-label">Uptime</span>
                    <span class="live-metric-value" style="flex:1;text-align:right;">${formatUptime(h.uptime)}</span>
                </div></div>`;
        }
        const cells = [];
        if (avail.includes('cpu_pct')) {
            const c = h.cpu > 90 ? 'text-danger' : h.cpu > 75 ? 'text-warning' : '';
            const v = h.cpu != null ? h.cpu.toFixed(0) + '%' : '—';
            cells.push(`<div class="col"><div class="text-muted">CPU</div><div class="fw-bold ${c}">${v}</div></div>`);
        }
        if (avail.includes('mem_pct')) {
            const c = h.mem > 92 ? 'text-danger' : h.mem > 80 ? 'text-warning' : '';
            const v = h.mem != null ? h.mem.toFixed(0) + '%' : '—';
            cells.push(`<div class="col"><div class="text-muted">Mem</div><div class="fw-bold ${c}">${v}</div></div>`);
        }
        if (avail.includes('temp_c')) {
            const c = h.temp > 85 ? 'text-danger' : h.temp > 70 ? 'text-warning' : '';
            const v = h.temp != null ? h.temp.toFixed(0) + '°C' : '—';
            cells.push(`<div class="col"><div class="text-muted">Temp</div><div class="fw-bold ${c}">${v}</div></div>`);
        }
        return `<div class="live-block">
            <div class="live-block-header">
                <span><i class="bi bi-heart-pulse"></i> Core Health</span>
                <span class="live-block-meta">${relativeTime(h.ts)}</span>
            </div>
            <div class="row g-2 small">
                ${cells.join('')}
                <div class="col"><div class="text-muted">Uptime</div><div class="fw-bold small">${formatUptime(h.uptime)}</div></div>
            </div></div>`;
    }

    function renderTcpBlock(device) {
        const tcp = device.tcp || [];
        if (tcp.length === 0) return '';
        const badges = tcp.map(t => {
            const cls = t.is_open ? 'bg-success' : 'bg-danger';
            const icon = t.is_open ? 'unlock-fill' : 'lock-fill';
            return `<span class="badge ${cls} me-1 mb-1"><i class="bi bi-${icon}"></i> ${t.port}</span>`;
        }).join('');
        return `<div class="live-block">
            <div class="live-block-header"><span><i class="bi bi-hdd-network"></i> TCP</span></div>
            <div class="small">${badges}</div></div>`;
    }

    /**
     * Bloque de clientes AP.
     *
     * Se muestran como máximo MAX_AP_CLIENTS clientes, ordenados con
     * los online primero y luego por nombre. Si hay más de
     * MAX_AP_CLIENTS en total, se añade un botón "Ver todos" que
     * redirige a la página de interfaces del equipo (solo si
     * `interfacesUrlTemplate` está configurado).
     *
     * La tabla compacta solo muestra 7 columnas (nombre, IP, signal,
     * CCQ, TX, RX, estado). Los detalles completos (distancia, airMAX,
     * SNR, noise) se ven en la página de interfaces del equipo.
     */
    function renderApClientsBlock(device) {
        if (!device.ap_clients || device.ap_clients.length === 0) return '';

        const clients = device.ap_clients;
        const total = clients.length;
        const onlineCount = clients.filter(c => c.online).length;
        const hasMore = total > MAX_AP_CLIENTS;
        const interfacesUrl = _deviceInterfacesUrl(device.id);

        // Ordenar: online primero, luego por nombre
        const sorted = [...clients].sort((a, b) => {
            if (a.online !== b.online) return b.online - a.online;
            const na = (a.name || a.hostname || a.mac || '').toLowerCase();
            const nb = (b.name || b.hostname || b.mac || '').toLowerCase();
            return na.localeCompare(nb);
        });
        const toShow = sorted.slice(0, MAX_AP_CLIENTS);

        const rows = toShow.map(c => {
            const rowCls = c.online ? '' : 'opacity-50';
            const sigN = c.signal;
            const sigC = sigN == null ? '' : sigN < -80 ? 'text-danger' : sigN < -70 ? 'text-warning' : 'text-success';
            const ccqN = c.ccq;
            const ccqC = ccqN == null ? '' : ccqN < 50 ? 'text-danger' : ccqN < 80 ? 'text-warning' : 'text-success';
            const displayName = c.name || c.hostname || c.mac || '—';

            return `<tr class="${rowCls}">
                <td class="small">
                    <div class="text-truncate" style="max-width:150px;" title="${escapeHtml(displayName)}">
                        ${escapeHtml(displayName)}
                    </div>
                </td>
                <td class="small">${escapeHtml(c.ip) || '—'}</td>
                <td class="text-end ${sigC} small">${sigN != null ? sigN.toFixed(0) + ' dBm' : '—'}</td>
                <td class="text-end ${ccqC} small">${ccqN != null ? ccqN.toFixed(0) + '%' : '—'}</td>
                <td class="text-end small">${formatBps(c.tx_rate)}</td>
                <td class="text-end small">${formatBps(c.rx_rate)}</td>
                <td class="text-center">${c.online
                    ? '<span class="badge bg-success" style="font-size:0.65rem;">Online</span>'
                    : '<span class="badge bg-secondary" style="font-size:0.65rem;">Offline</span>'}</td>
            </tr>`;
        }).join('');

        const moreButton = (hasMore && interfacesUrl) ? `
            <div class="text-center mt-2">
                <a href="${interfacesUrl}" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-broadcast-pin"></i>
                    Ver todos los ${total} clientes
                    <i class="bi bi-arrow-right"></i>
                </a>
            </div>
        ` : '';

        const metaLabel = hasMore
            ? `${onlineCount}/${total} en línea · mostrando ${toShow.length}`
            : `${onlineCount}/${total} en línea`;

        return `<div class="live-block">
            <div class="live-block-header">
                <span><i class="bi bi-people-fill text-info"></i> Clientes AP</span>
                <span class="live-block-meta">${metaLabel}</span>
            </div>
            <div class="table-responsive">
                <table class="table table-sm table-borderless mb-0">
                    <thead><tr class="small text-muted">
                        <th>Nombre</th><th>IP</th>
                        <th class="text-end">Señal</th><th class="text-end">CCQ</th>
                        <th class="text-end">TX</th><th class="text-end">RX</th>
                        <th class="text-center">Estado</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            ${moreButton}
        </div>`;
    }

    // ============================================================
    // CONVENIENCIA: TODOS LOS BLOQUES
    // ============================================================
    function renderAllBlocks(device) {
        const chartMode = _currentViewMode === 'chart';
        return (
            renderWirelessBlock(device.wireless_info) +
            renderRadioBlock(device, chartMode) +
            renderIcmpBlock(device, chartMode) +
            (device.is_wireless_link
                ? renderApClientsBlock(device)
                : renderTrafficBlock(device, chartMode)) +
            renderHealthBlock(device, chartMode) +
            renderTcpBlock(device)
        );
    }

    // ============================================================
    // VIEW MODE
    // ============================================================
    function initViewMode(callback) {
        let mode = 'static';
        try {
            const s = localStorage.getItem('cf-live-view-mode');
            if (s === 'chart' || s === 'static') mode = s;
        } catch (e) {}
        _currentViewMode = mode;
        _onViewModeChange = callback || null;

        const radio = document.getElementById(mode === 'chart' ? 'mode-chart' : 'mode-static');
        if (radio) radio.checked = true;

        document.querySelectorAll('input[name="view-mode"]').forEach(r => {
            r.addEventListener('change', () => {
                if (r.checked) setViewMode(r.value);
            });
        });
    }

    function setViewMode(mode) {
        if (mode !== 'static' && mode !== 'chart') return;
        _currentViewMode = mode;
        const radio = document.getElementById(mode === 'chart' ? 'mode-chart' : 'mode-static');
        if (radio) radio.checked = true;
        try { localStorage.setItem('cf-live-view-mode', mode); } catch (e) {}
        if (_onViewModeChange) _onViewModeChange(mode);
    }

    // ============================================================
    // API PÚBLICA
    // ============================================================
    return {
        configure(opts) {
            if (opts.sparklineUrl) _sparklineUrl = opts.sparklineUrl;
            if (opts.sparklineMinutes) _sparklineMinutes = opts.sparklineMinutes;
            if (opts.interfacesUrlTemplate) _interfacesUrlTemplate = opts.interfacesUrlTemplate;
        },
        formatBps, formatUptime, relativeTime, escapeHtml,
        utilColor, signalColor, signalStrokeColor,
        observeSparklines, refreshVisibleSparklines,
        resetSparklineCache: () => _sparklineCache.clear(),
        renderAllBlocks,
        initViewMode, setViewMode,
        getViewMode: () => _currentViewMode,
    };
})();