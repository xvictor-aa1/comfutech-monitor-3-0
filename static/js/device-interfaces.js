/**
 * device-interfaces.js — Lógica de la página de interfaces / clientes AP.
 *
 * Usado por: inventario/device_interfaces.html
 *
 * Depende de:
 *   - Toasts (show, success, warning, danger, info)
 *
 * API pública:
 *   DeviceInterfaces.init(config)
 *   DeviceInterfaces.resetToWan()
 *   DeviceInterfaces.loadApClients(manual)
 *   DeviceInterfaces.selectAll()
 *   DeviceInterfaces.deselectAll()
 *   DeviceInterfaces.selectPhysical()
 *   DeviceInterfaces.toggleDashboardInterface(btn)
 *
 * config:
 *   {
 *     deviceId: number,               // ID del equipo actual
 *     apClientsTotal: number,         // Total inicial de clientes AP
 *     urls: {
 *       live:              string,    // endpoint de devices_live
 *       setDashboard:      string,    // URL con placeholder __IFACE__
 *                                     // Ej: "/equipos/5/interface/__IFACE__/set-dashboard/"
 *     },
 *     refreshInterval: number,        // ms, default 10000
 *     toastContainerId: string,       // default "iface-toast-container"
 *   }
 *
 * Carga:
 *   <script src="{% static 'js/toasts.js' %}"></script>
 *   <script src="{% static 'js/device-interfaces.js' %}"></script>
 */

window.DeviceInterfaces = (function () {
    'use strict';

    // ============================================================
    // CONFIGURACIÓN
    // ============================================================
    let _config = {
        deviceId: null,
        apClientsTotal: 0,
        urls: {
            live: '',
            setDashboard: '',
        },
        refreshInterval: 10000,
        toastContainerId: 'iface-toast-container',
    };

    // ============================================================
    // ESTADO INTERNO
    // ============================================================
    let _apRefreshTimer = null;
    let _apAutoRefreshEnabled = true;

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

    function formatDistance(m) {
        if (m === null || m === undefined) return '—';
        if (m >= 1000) return (m / 1000).toFixed(1) + ' km';
        return m.toFixed(0) + ' m';
    }

    function escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function signalColor(s) {
        if (s === null || s === undefined) return '';
        if (s < -80) return 'text-danger';
        if (s < -70) return 'text-warning';
        return 'text-success';
    }

    function ccqColor(c) {
        if (c === null || c === undefined) return '';
        if (c < 50) return 'text-danger';
        if (c < 80) return 'text-warning';
        return 'text-success';
    }

    function noiseColor(n) {
        if (n === null || n === undefined) return '';
        if (n > -80) return 'text-danger';
        if (n > -90) return 'text-warning';
        return '';
    }

    function snrColor(s) {
        if (s === null || s === undefined) return '';
        if (s < 15) return 'text-danger';
        if (s < 25) return 'text-warning';
        return 'text-success';
    }

    function clientDisplayName(c) {
        return c.name || c.hostname || c.mac || '—';
    }

    function _toast(opts) {
        if (typeof Toasts === 'undefined') {
            if (opts.message) alert(opts.message);
            return;
        }
        Toasts.show(Object.assign({
            containerId: _config.toastContainerId,
            showTime: true,
            autohide: true,
            delay: 4000,
        }, opts));
    }

    // ============================================================
    // CLIENTES AP — POLLING
    // ============================================================
    async function loadApClients(manual) {
        const btn = document.getElementById('ap-btn-refresh');

        if (manual && btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        }

        try {
            const response = await fetch(_config.urls.live, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' },
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            const myDevice = (data.devices || []).find(d => d.id === _config.deviceId);
            if (!myDevice) {
                console.warn('Device no encontrado en la respuesta del servidor.');
                return;
            }

            const clients = myDevice.ap_clients || [];
            renderApClients(clients);

            const ts = new Date(data.timestamp);
            const el = document.getElementById('ap-last-update');
            if (el) el.textContent = ts.toLocaleTimeString('es-VE');

        } catch (e) {
            console.error('Error cargando clientes AP:', e);
            const el = document.getElementById('ap-last-update');
            if (el) el.textContent = 'error';
        } finally {
            if (manual && btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Recargar';
            }
        }
    }

    /**
     * Renderiza la tabla completa de clientes AP (13 columnas).
     * @param {Array} clients
     */
    function renderApClients(clients) {
        const tbody = document.getElementById('ap-clients-tbody');
        if (!tbody) return;

        const online = clients.filter(c => c.online).length;
        const total = clients.length;

        const statOnlineEl = document.getElementById('ap-stat-online');
        const statTotalEl = document.getElementById('ap-stat-total');
        const badgeEl = document.getElementById('ap-count-badge');
        const tabCountEl = document.getElementById('ap-tab-count');

        if (statOnlineEl) statOnlineEl.textContent = online;
        if (statTotalEl) statTotalEl.textContent = total;
        if (badgeEl) badgeEl.textContent = total;
        if (tabCountEl) tabCountEl.textContent = total;

        if (clients.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="13" class="text-center text-muted py-5">
                        <i class="bi bi-broadcast-pin" style="font-size: 3rem;"></i>
                        <p class="mt-3 mb-2">No hay clientes AP registrados.</p>
                    </td>
                </tr>
            `;
            return;
        }

        // Ordenar: online primero, luego por nombre.
        clients.sort((a, b) => {
            if (a.online !== b.online) return b.online - a.online;
            const na = (clientDisplayName(a) || '').toLowerCase();
            const nb = (clientDisplayName(b) || '').toLowerCase();
            return na.localeCompare(nb);
        });

        tbody.innerHTML = clients.map(c => {
            const rowCls = c.online ? '' : 'opacity-50';

            const signalVal = c.signal !== null && c.signal !== undefined
                ? c.signal.toFixed(0) + ' dBm' : '—';
            const ccqVal = c.ccq !== null && c.ccq !== undefined
                ? c.ccq.toFixed(0) + '%' : '—';
            const noiseVal = c.noise !== null && c.noise !== undefined
                ? c.noise.toFixed(0) + ' dBm' : '—';
            const snrVal = c.snr !== null && c.snr !== undefined
                ? c.snr.toFixed(0) + ' dB' : '—';
            const rxVal = formatBps(c.rx_rate);
            const txVal = formatBps(c.tx_rate);
            const distVal = formatDistance(c.distance);
            const amQVal = c.airmax_quality !== null && c.airmax_quality !== undefined
                ? c.airmax_quality.toFixed(0) + '%' : '—';
            const amCVal = c.airmax_capacity !== null && c.airmax_capacity !== undefined
                ? c.airmax_capacity.toFixed(0) + '%' : '—';

            return `
                <tr class="${rowCls}" data-mac="${escapeHtml(c.mac)}">
                    <td><code class="small">${escapeHtml(c.mac)}</code></td>
                    <td class="small">
                        <div class="text-truncate" style="max-width: 220px;"
                             title="${escapeHtml(clientDisplayName(c))}">
                            ${escapeHtml(clientDisplayName(c))}
                        </div>
                    </td>
                    <td><code class="small">${escapeHtml(c.ip) || 'desconocido'}</code></td>
                    <td class="text-end small ${signalColor(c.signal)}">${signalVal}</td>
                    <td class="text-end small ${ccqColor(c.ccq)}">${ccqVal}</td>
                    <td class="text-end small ${noiseColor(c.noise)}">${noiseVal}</td>
                    <td class="text-end small ${snrColor(c.snr)}">${snrVal}</td>
                    <td class="text-end small text-success">↓ ${rxVal}</td>
                    <td class="text-end small text-warning">↑ ${txVal}</td>
                    <td class="text-end small text-muted">${distVal}</td>
                    <td class="text-end small">${amQVal}</td>
                    <td class="text-end small">${amCVal}</td>
                    <td class="text-center">
                        ${c.online
                            ? '<span class="badge bg-success">Online</span>'
                            : '<span class="badge bg-secondary">Offline</span>'}
                    </td>
                </tr>
            `;
        }).join('');
    }

    function startApAutoRefresh() {
        stopApAutoRefresh();
        _apAutoRefreshEnabled = true;
        _apRefreshTimer = setInterval(
            () => loadApClients(false),
            _config.refreshInterval
        );
    }

    function stopApAutoRefresh() {
        if (_apRefreshTimer) {
            clearInterval(_apRefreshTimer);
            _apRefreshTimer = null;
        }
        _apAutoRefreshEnabled = false;
    }

    // ============================================================
    // IF-MIB — SELECCIÓN
    // ============================================================
    function updateCount() {
        const checkboxes = document.querySelectorAll('.interface-checkbox');
        const checked = document.querySelectorAll('.interface-checkbox:checked');
        const el = document.getElementById('selected-count');
        if (el) el.textContent = checked.length;

        checkboxes.forEach(cb => {
            const row = cb.closest('tr');
            if (!row) return;
            if (cb.checked) row.classList.add('interface-monitored');
            else row.classList.remove('interface-monitored');
        });
    }

    function selectAll() {
        document.querySelectorAll('.interface-checkbox').forEach(cb => { cb.checked = true; });
        updateCount();
    }

    function deselectAll() {
        document.querySelectorAll('.interface-checkbox').forEach(cb => { cb.checked = false; });
        updateCount();
    }

    function selectPhysical() {
        document.querySelectorAll('.interface-checkbox').forEach(cb => {
            const speed = parseInt(cb.dataset.speed) || 0;
            cb.checked = speed > 0;
        });
        updateCount();
    }

    // ============================================================
    // INTERFAZ DESTACADA (⭐)
    // ============================================================
    function _buildSetDashboardUrl(interfaceId) {
        if (!_config.urls.setDashboard) return null;
        return _config.urls.setDashboard.replace('__IFACE__', String(interfaceId));
    }

    /**
     * Marca/desmarca una interfaz como destacada del dashboard.
     * @param {HTMLButtonElement} btn
     */
    async function toggleDashboardInterface(btn) {
        if (!btn) return;

        const interfaceId = parseInt(btn.dataset.interfaceId, 10);
        const isCurrent = btn.dataset.isDashboard === 'true';
        const targetId = isCurrent ? 0 : interfaceId;

        const url = _buildSetDashboardUrl(targetId);
        if (!url) {
            console.error('URL de set-dashboard no configurada.');
            return;
        }

        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

        try {
            const csrfToken = typeof getCookie === 'function'
                ? getCookie('csrftoken')
                : '';

            const response = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrfToken },
            });

            const data = await response.json();

            if (!data.ok) {
                _toast({
                    severity: 'danger',
                    title: 'Interfaz destacada',
                    message: data.error || 'Error al marcar la interfaz.',
                });
                return;
            }

            updateAllStarButtons(data.dashboard_interface_id);
            updateDashboardBadges(data.dashboard_interface_id);
            updateHighlightWanButton();

            _toast({
                severity: 'success',
                title: 'Interfaz destacada',
                message: data.message,
            });

        } catch (e) {
            console.error('Error marcando interfaz:', e);
            _toast({
                severity: 'danger',
                title: 'Interfaz destacada',
                message: 'Error de red. Intenta de nuevo.',
            });
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    function updateAllStarButtons(dashboardId) {
        document.querySelectorAll('.btn-dashboard-star').forEach(btn => {
            const btnIfaceId = parseInt(btn.dataset.interfaceId, 10);
            const isNow = dashboardId !== null && btnIfaceId === dashboardId;

            btn.dataset.isDashboard = isNow ? 'true' : 'false';
            btn.classList.toggle('btn-warning', isNow);
            btn.classList.toggle('btn-outline-secondary', !isNow);

            const icon = btn.querySelector('i');
            if (icon) {
                icon.classList.toggle('bi-star-fill', isNow);
                icon.classList.toggle('bi-star', !isNow);
            }

            btn.title = isNow
                ? 'Quitar como destacada'
                : 'Marcar como destacada del dashboard';
        });
    }

    function updateDashboardBadges(dashboardId) {
        document.querySelectorAll('.dashboard-badge').forEach(b => b.remove());
        if (dashboardId === null) return;

        const row = document.querySelector(
            `tr[data-interface-id="${dashboardId}"]`
        );
        if (!row) return;

        const cells = row.querySelectorAll('td');
        let targetCell = null;
        for (const cell of cells) {
            if (cell.querySelector('strong')) {
                targetCell = cell;
                break;
            }
        }
        if (!targetCell) return;

        const badge = document.createElement('span');
        badge.className = 'badge bg-warning text-dark ms-1 dashboard-badge';
        badge.title = 'Esta es la interfaz destacada del dashboard';
        badge.style.fontSize = '0.6rem';
        badge.innerHTML = '<i class="bi bi-star-fill"></i> Destacada';
        targetCell.appendChild(badge);
    }

    // ============================================================
    // DESTACAR WAN AUTOMÁTICAMENTE
    // ============================================================
    const WAN_NAME_CANDIDATES = [
        'ether1', 'wan', 'sfp-sfpplus1', 'eth0', 'eth1',
        'ether2', 'internet', 'uplink',
    ];

    function _getRowName(row) {
        const cells = row.querySelectorAll('td');
        for (const cell of cells) {
            const strong = cell.querySelector('strong');
            if (strong) return strong.textContent.trim().toLowerCase();
        }
        return '';
    }

    function _findWanRow() {
        const rows = Array.from(document.querySelectorAll('tr[data-interface-id]'));
        if (rows.length === 0) return null;

        for (const candidate of WAN_NAME_CANDIDATES) {
            const found = rows.find(row => {
                const name = _getRowName(row);
                return name === candidate || name.includes(candidate);
            });
            if (found) return found;
        }
        return null;
    }

    async function resetToWan() {
        const btn = document.getElementById('btn-highlight-wan');
        if (!btn) return;

        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

        try {
            const rows = Array.from(document.querySelectorAll('tr[data-interface-id]'));
            if (rows.length === 0) {
                _toast({
                    severity: 'warning',
                    title: 'Interfaz destacada',
                    message: 'No hay interfaces en la tabla. Ejecuta Discovery primero.',
                });
                return;
            }

            let targetRow = _findWanRow();

            // Fallback 1: primera física monitoreada.
            if (!targetRow) {
                targetRow = rows.find(row => {
                    const cb = row.querySelector('.interface-checkbox');
                    if (!cb) return false;
                    const speed = parseInt(cb.dataset.speed) || 0;
                    return speed > 0 && cb.checked;
                });
            }

            // Fallback 2: primera interfaz activa (up).
            if (!targetRow) {
                targetRow = rows.find(row => {
                    const statusText = row.textContent.toLowerCase();
                    return statusText.includes('up') && !statusText.includes('down');
                });
            }

            if (!targetRow) {
                _toast({
                    severity: 'warning',
                    title: 'Interfaz destacada',
                    message: 'No se encontró una interfaz WAN clara. ' +
                             'Marca manualmente con el botón ⭐ de la tabla.',
                });
                return;
            }

            const starBtn = targetRow.querySelector('.btn-dashboard-star');
            if (!starBtn) {
                _toast({
                    severity: 'danger',
                    title: 'Interfaz destacada',
                    message: 'No se pudo encontrar el botón ⭐ de la fila. ' +
                             'Refresca la página e intenta de nuevo.',
                });
                return;
            }

            const isCurrentlyDashboard = starBtn.dataset.isDashboard === 'true';
            const ifaceName = _getRowName(targetRow);

            if (isCurrentlyDashboard) {
                _toast({
                    severity: 'info',
                    title: 'Interfaz destacada',
                    message: `"${ifaceName}" ya es la interfaz destacada del dashboard.`,
                });
                return;
            }

            starBtn.click();

            targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });

            targetRow.style.transition = 'background-color 0.3s ease';
            const originalBg = targetRow.style.backgroundColor;
            targetRow.style.backgroundColor = 'rgba(255, 193, 7, 0.25)';
            setTimeout(() => {
                targetRow.style.backgroundColor = originalBg;
            }, 1200);

        } catch (e) {
            console.error('Error destacando WAN:', e);
            _toast({
                severity: 'danger',
                title: 'Interfaz destacada',
                message: 'Error al destacar la WAN. Intenta manualmente.',
            });
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    function updateHighlightWanButton() {
        const btn = document.getElementById('btn-highlight-wan');
        if (!btn) return;

        const targetRow = _findWanRow();

        if (!targetRow) {
            btn.classList.add('disabled');
            btn.title = 'No se encontró una interfaz WAN. Marca manualmente con ⭐.';
            return;
        }

        const starBtn = targetRow.querySelector('.btn-dashboard-star');
        const isDashboard = starBtn && starBtn.dataset.isDashboard === 'true';

        if (isDashboard) {
            btn.classList.remove('btn-outline-warning');
            btn.classList.add('btn-warning');
            btn.innerHTML = '<i class="bi bi-star-fill"></i>' +
                '<span class="d-none d-md-inline"> WAN destacada</span>';
            btn.title = 'La WAN ya es la interfaz destacada del dashboard';
        } else {
            btn.classList.remove('btn-warning');
            btn.classList.add('btn-outline-warning');
            btn.innerHTML = '<i class="bi bi-star-fill"></i>' +
                '<span class="d-none d-md-inline"> Destacar WAN</span>';
            btn.title = 'Marcar la interfaz WAN/ether1 como destacada del dashboard';
        }
    }

    // ============================================================
    // INIT
    // ============================================================
    function init(config) {
        config = config || {};

        // Merge config.
        Object.keys(config).forEach(k => {
            if (k === 'urls') {
                _config.urls = Object.assign({}, _config.urls, config.urls || {});
            } else {
                _config[k] = config[k];
            }
        });

        // Exponer funciones que el template llama desde onclick.
        window.resetToWan = resetToWan;
        window.loadApClients = loadApClients;
        window.selectAll = selectAll;
        window.deselectAll = deselectAll;
        window.selectPhysical = selectPhysical;
        window.toggleDashboardInterface = toggleDashboardInterface;

        // ========================================================
        // IF-MIB: listeners y conteo inicial
        // ========================================================
        document.querySelectorAll('.interface-checkbox').forEach(cb => {
            cb.addEventListener('change', updateCount);
        });
        updateCount();

        // ========================================================
        // Botones ⭐
        // ========================================================
        document.querySelectorAll('.btn-dashboard-star').forEach(btn => {
            btn.addEventListener('click', () => toggleDashboardInterface(btn));
        });
        updateHighlightWanButton();

        // ========================================================
        // Clientes AP
        // ========================================================
        const apTable = document.getElementById('ap-clients-table');
        if (!apTable) return;

        // Carga inicial solo si hay clientes estáticos.
        if (_config.apClientsTotal > 0) {
            loadApClients(false);
        }

        // Toggle de auto-refresh.
        const autoToggle = document.getElementById('ap-auto-refresh');
        if (autoToggle) {
            autoToggle.addEventListener('change', () => {
                if (autoToggle.checked) startApAutoRefresh();
                else stopApAutoRefresh();
            });
            if (autoToggle.checked) startApAutoRefresh();
        }

        // Pausar/reanudar al cambiar de pestaña.
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                if (_apRefreshTimer) stopApAutoRefresh();
            } else {
                const toggle = document.getElementById('ap-auto-refresh');
                if (toggle && toggle.checked) {
                    startApAutoRefresh();
                    loadApClients(false);
                }
            }
        });
    }

    // ============================================================
    // API PÚBLICA
    // ============================================================
    return {
        init,
        resetToWan,
        loadApClients,
        selectAll,
        deselectAll,
        selectPhysical,
        toggleDashboardInterface,
    };
})();