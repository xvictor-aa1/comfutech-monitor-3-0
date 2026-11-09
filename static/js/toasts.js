/**
 * toasts.js — Notificaciones toast compartidas.
 *
 * Usado por:
 *   - core/dashboard.html
 *   - inventario/device_interfaces.html
 *
 * API pública:
 *   Toasts.configure({containerId, position, marginTop, zIndex,
 *                     defaultAutohide, defaultDelay})
 *   Toasts.show({message, severity, title, icon, subtitle, action,
 *                autohide, delay, showTime, id, containerId,
 *                position, marginTop, escapeMessage})
 *   Toasts.alert(alertData, {ruleUrlTemplate, alertListUrl, ...})
 *   Toasts.success/info/warning/danger(message, opts)
 *   Toasts.clear(opts)
 *
 * Carga:
 *   <script src="{% static 'js/toasts.js' %}"></script>
 *
 * Ejemplo mínimo:
 *   Toasts.success('Guardado correctamente');
 *   Toasts.info('Discovery completado', { title: 'Listo' });
 *   Toasts.alert(alert, { alertListUrl: '/alertas/' });
 */

window.Toasts = (function () {
    'use strict';

    // ============================================================
    // CONFIGURACIÓN GLOBAL
    // ============================================================
    let _config = {
        containerId: 'toast-container',
        position: 'top-0 end-0',
        marginTop: 60,
        zIndex: 1090,
        defaultAutohide: true,
        defaultDelay: 5000,
    };

    // ============================================================
    // ESTILOS POR SEVERIDAD
    // ============================================================
    const STYLES = {
        critical: {
            icon: 'bi-fire',
            header: 'bg-danger text-white',
            title: '🔴 Alerta Crítica',
        },
        danger: {
            icon: 'bi-x-circle-fill',
            header: 'bg-danger text-white',
            title: '🔴 Error',
        },
        warning: {
            icon: 'bi-exclamation-triangle-fill',
            header: 'bg-warning text-dark',
            title: '🟡 Advertencia',
        },
        success: {
            icon: 'bi-check-circle-fill',
            header: 'bg-success text-white',
            title: '🟢 Éxito',
        },
        info: {
            icon: 'bi-info-circle-fill',
            header: 'bg-info text-white',
            title: '🔵 Info',
        },
    };

    // ============================================================
    // HELPERS
    // ============================================================
    function _escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /**
     * Devuelve (o crea) el contenedor de toasts.
     * Soporta overrides por llamada: containerId, position, marginTop, zIndex.
     */
    function _getOrCreateContainer(opts) {
        const containerId = (opts && opts.containerId) || _config.containerId;
        const position = (opts && opts.position) || _config.position;
        const marginTop = (opts && opts.marginTop !== undefined)
            ? opts.marginTop
            : _config.marginTop;
        const zIndex = (opts && opts.zIndex) || _config.zIndex;

        let container = document.getElementById(containerId);
        if (container) return container;

        container = document.createElement('div');
        container.id = containerId;
        container.className = `toast-container position-fixed ${position} p-3`;
        container.style.zIndex = String(zIndex);
        if (marginTop) container.style.marginTop = marginTop + 'px';
        document.body.appendChild(container);
        return container;
    }

    /**
     * Construye el HTML de un toast y devuelve metadata.
     */
    function _buildToast(opts) {
        const severity = opts.severity || 'info';
        const style = STYLES[severity] || STYLES.info;
        const title = opts.title || style.title;
        const icon = opts.icon || style.icon;
        const headerClass = opts.headerClass || style.header;
        const showTime = opts.showTime !== false;
        const autohide = (opts.autohide !== undefined)
            ? opts.autohide
            : _config.defaultAutohide;
        const delay = (opts.delay !== undefined)
            ? opts.delay
            : _config.defaultDelay;

        const id = opts.id || (
            'toast-' + Date.now() + '-' +
            Math.random().toString(36).slice(2, 8)
        );

        const messageHtml = (opts.escapeMessage === false)
            ? (opts.message || '')
            : _escapeHtml(opts.message || '');

        const subtitleHtml = opts.subtitle || '';

        const actionHtml = opts.action ? `
            <div class="mt-2 text-end">
                <a href="${_escapeHtml(opts.action.href || '#')}"
                   class="btn btn-sm btn-outline-secondary">
                    ${_escapeHtml(opts.action.label || 'Ver')}
                    ${opts.action.icon ? `<i class="bi ${opts.action.icon}"></i>` : ''}
                </a>
            </div>
        ` : '';

        return {
            id,
            html: `
                <div id="${id}" class="toast" role="alert" aria-live="assertive"
                     aria-atomic="true"
                     data-bs-autohide="${autohide}"
                     data-bs-delay="${delay}">
                    <div class="toast-header ${headerClass}">
                        <i class="bi ${icon} me-2"></i>
                        <strong class="me-auto">${title}</strong>
                        ${showTime ? '<small>ahora</small>' : ''}
                        <button type="button" class="btn-close btn-close-white ms-2"
                                data-bs-dismiss="toast"></button>
                    </div>
                    <div class="toast-body small">
                        ${subtitleHtml}
                        <div>${messageHtml}</div>
                        ${actionHtml}
                    </div>
                </div>
            `,
            autohide,
            delay,
        };
    }

    // ============================================================
    // SHOW GENÉRICO
    // ============================================================
    /**
     * Muestra un toast.
     *
     * Opciones principales:
     *   - message       (requerido) Texto del cuerpo.
     *   - severity      'info' | 'success' | 'warning' | 'danger' | 'critical'
     *                   (default: 'info').
     *   - title         Título del header (default: según severidad).
     *   - icon          Clase de icono Bootstrap (ej: 'bi-check-circle-fill').
     *   - headerClass   Clase CSS del header (ej: 'bg-danger text-white').
     *   - subtitle      HTML que se inserta ANTES del mensaje (ej: enlace a regla).
     *   - action        { label, href, icon } — botón al pie del cuerpo.
     *   - autohide      bool (default: true).
     *   - delay         ms (default: 5000).
     *   - showTime      bool (default: true) — muestra "ahora" en el header.
     *   - id            ID del elemento (default: autogenerado).
     *   - escapeMessage bool (default: true) — escapa el mensaje con HTML entities.
     *
     * Opciones de contenedor (sobrescriben la config global):
     *   - containerId, position, marginTop, zIndex
     *
     * @param {object} opts
     * @returns {bootstrap.Toast|null}
     */
    function show(opts) {
        if (!opts || !opts.message) return null;
        if (typeof bootstrap === 'undefined' || !bootstrap.Toast) {
            console.warn('[Toasts] Bootstrap Toast no disponible');
            return null;
        }

        // Evitar duplicados si el caller pasa un id existente.
        if (opts.id && document.getElementById(opts.id)) return null;

        const container = _getOrCreateContainer(opts);
        const built = _buildToast(opts);
        container.insertAdjacentHTML('beforeend', built.html);

        const el = document.getElementById(built.id);
        if (!el) return null;

        const toast = new bootstrap.Toast(el, {
            autohide: built.autohide,
            delay: built.delay,
        });
        toast.show();

        el.addEventListener('hidden.bs.toast', () => el.remove());
        return toast;
    }

    // ============================================================
    // ALERT (especializado)
    // ============================================================
    /**
     * Muestra un toast para una alerta del dashboard.
     *
     * Formato del toast:
     *   - Título según severidad (🔴/🟡/🔵).
     *   - Subtítulo: enlace a la regla (si tiene rule_id + rule_name).
     *   - Mensaje de la alerta.
     *   - Botón "Ver alertas" que filtra el listado por rule_id.
     *
     * Opciones:
     *   - ruleUrlTemplate  URL template para el enlace de la regla.
     *                      Default: '/alertas/?rule_id={id}'
     *   - alertListUrl     URL base del listado de alertas.
     *                      Default: '/alertas/'
     *   - id               ID del toast (útil para deduplicar).
     *
     * El toast es PERSISTENTE (autohide: false) porque las alertas
     * críticas deben ser vistas por el operador.
     *
     * @param {object} alertData  {id, severity, rule_id, rule_name, message}
     * @param {object} [opts]
     * @returns {bootstrap.Toast|null}
     */
    function alertToast(alertData, opts) {
        opts = opts || {};
        if (!alertData) return null;

        const severity = alertData.severity || 'info';
        const ruleUrlTemplate = opts.ruleUrlTemplate || '/alertas/?rule_id={id}';
        const alertListUrl = opts.alertListUrl || '/alertas/';

        // --- Subtítulo: enlace a la regla ---
        let subtitle = '';
        if (alertData.rule_id && alertData.rule_name) {
            const url = ruleUrlTemplate.replace('{id}', alertData.rule_id);
            subtitle = `<div class="mb-1"><strong><a href="${_escapeHtml(url)}" class="text-decoration-none"><i class="bi bi-shield-check"></i> ${_escapeHtml(alertData.rule_name)}</a></strong></div>`;
        } else if (alertData.rule_name) {
            subtitle = `<div class="mb-1"><strong><span class="text-muted"><i class="bi bi-shield"></i> ${_escapeHtml(alertData.rule_name)}</span></strong></div>`;
        }

        // --- Botón "Ver alertas" ---
        const actionUrl = alertData.rule_id
            ? alertListUrl + (alertListUrl.includes('?') ? '&' : '?') +
              'rule_id=' + alertData.rule_id
            : alertListUrl;
        const action = {
            label: 'Ver alertas',
            href: actionUrl,
            icon: 'bi-arrow-right',
        };

        return show({
            id: opts.id || (alertData.id ? `toast-alert-${alertData.id}` : undefined),
            severity,
            title: opts.title,
            message: alertData.message,
            subtitle,
            action,
            autohide: false,
            escapeMessage: true,
            showTime: true,
            containerId: opts.containerId,
            position: opts.position,
            marginTop: opts.marginTop,
        });
    }

    // ============================================================
    // CONFIGURE / CLEAR
    // ============================================================
    function configure(opts) {
        if (!opts) return;
        Object.keys(opts).forEach(k => {
            if (k in _config) _config[k] = opts[k];
        });
    }

    function clear(opts) {
        const containerId = (opts && opts.containerId) || _config.containerId;
        const container = document.getElementById(containerId);
        if (container) container.innerHTML = '';
    }

    // ============================================================
    // ATAJOS POR SEVERIDAD
    // ============================================================
    function _shortcut(severity) {
        return function (message, opts) {
            return show(Object.assign(
                { message, severity },
                opts || {}
            ));
        };
    }

    // ============================================================
    // API PÚBLICA
    // ============================================================
    return {
        configure,
        show,
        alert: alertToast,
        clear,
        success: _shortcut('success'),
        info:    _shortcut('info'),
        warning: _shortcut('warning'),
        danger:  _shortcut('danger'),
    };
})();