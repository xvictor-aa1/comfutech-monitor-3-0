/**
 * tables.js — Utilidades compartidas para tablas de listados.
 *
 * Usado por:
 *   - alertas/alert_list.html
 *   - alertas/rule_list.html
 *   - core/user_list.html
 *   - inventario/device_list.html
 *   - inventario/device_model_list.html
 *
 * API pública:
 *   Tables.initQuickFilter(opts)        → filtro rápido en el cliente
 *   Tables.initSelection(opts)          → checkboxes + "seleccionar todos" + contador
 *   Tables.confirmBulk(opts)            → confirmación de acciones masivas
 *   Tables.initTooltips()               → tooltips de Bootstrap
 *   Tables.initKeyboardShortcuts(opts)  → atajos de teclado (/ y Esc)
 *
 * Carga:
 *   <script src="{% static 'js/tables.js' %}"></script>
 *
 * Ejemplo mínimo:
 *   Tables.initQuickFilter({
 *       inputId: 'quick-search',
 *       clearBtnId: 'quick-search-clear',
 *       counterId: 'live-count',
 *       rowSelector: 'tbody tr[data-rule-id]',
 *   });
 *
 *   Tables.initSelection({
 *       checkboxSelector: '.rule-checkbox',
 *       masterCheckboxId: 'select-all-rules',
 *       counterId: 'live-count',
 *       rowSelector: 'tbody tr[data-rule-id]',
 *   });
 */

window.Tables = (function () {
    'use strict';

    // ============================================================
    // HELPERS
    // ============================================================
    /**
     * Devuelve true si el elemento es visible (display !== 'none').
     * @param {HTMLElement} el
     * @returns {boolean}
     */
    function _isVisible(el) {
        return el && el.style.display !== 'none';
    }

    /**
     * Devuelve true si el evento proviene de un input/textarea/select.
     * Se usa en los atajos de teclado para no interferir con la escritura.
     * @param {KeyboardEvent} e
     * @returns {boolean}
     */
    function _isTypingTarget(e) {
        const tag = (e.target.tagName || '').toUpperCase();
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    }

    // ============================================================
    // 1. QUICK FILTER (búsqueda en el cliente)
    // ============================================================
    /**
     * Inicializa el filtro rápido sobre las filas de la tabla.
     *
     * Este filtro trabaja en el CLIENTE (no recarga la página) y solo
     * actúa sobre las filas de la página actual. Es complementario al
     * buscador avanzado del servidor.
     *
     * Opciones:
     *   - inputId       (requerido) ID del <input> de búsqueda.
     *   - clearBtnId    (opcional)  ID del botón "limpiar".
     *   - counterId     (opcional)  ID del span que muestra "N de M visibles".
     *   - tableId       (opcional)  ID de la tabla (default: cualquier <table>).
     *   - rowSelector   (requerido) Selector CSS de las filas a filtrar.
     *                              Ej: 'tbody tr[data-rule-id]'
     *   - minChars      (opcional)  Mínimo de caracteres para activar (default 0).
     *   - onFilter      (opcional)  Callback (visibleCount, totalCount) => void
     *
     * @param {object} opts
     * @returns {{ apply: Function, clear: Function }}
     */
    function initQuickFilter(opts) {
        opts = opts || {};
        const inputId = opts.inputId;
        const clearBtnId = opts.clearBtnId;
        const counterId = opts.counterId;
        const tableId = opts.tableId;
        const rowSelector = opts.rowSelector || 'tbody tr';
        const minChars = opts.minChars || 0;
        const onFilter = opts.onFilter;

        const input = inputId ? document.getElementById(inputId) : null;
        const table = tableId ? document.getElementById(tableId) : null;
        if (!input) {
            console.warn('[Tables] initQuickFilter: inputId no encontrado:', inputId);
            return { apply: () => {}, clear: () => {} };
        }

        const clearBtn = clearBtnId ? document.getElementById(clearBtnId) : null;
        const counter = counterId ? document.getElementById(counterId) : null;

        // Scope de búsqueda: la tabla específica o el documento.
        const scope = table || document;

        function applyFilter() {
            const q = (input.value || '').toLowerCase().trim();
            const rows = scope.querySelectorAll(rowSelector);
            let visible = 0;

            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                const match = !q || (q.length >= minChars && text.includes(q));
                row.style.display = match ? '' : 'none';
                if (match) visible++;
            });

            if (clearBtn) clearBtn.style.display = input.value ? 'block' : 'none';

            if (counter) {
                if (!q) {
                    counter.textContent = '';
                    counter.className = 'small text-muted';
                } else {
                    counter.textContent = `${visible} de ${rows.length} visibles`;
                    counter.className = visible === 0
                        ? 'small text-danger fw-bold'
                        : 'small text-success';
                }
            }

            if (typeof onFilter === 'function') {
                try { onFilter(visible, rows.length); } catch (e) { console.warn(e); }
            }
        }

        function clearFilter() {
            input.value = '';
            applyFilter();
            input.focus();
        }

        input.addEventListener('input', applyFilter);
        if (clearBtn) clearBtn.addEventListener('click', clearFilter);

        return {
            apply: applyFilter,
            clear: clearFilter,
        };
    }

    // ============================================================
    // 2. SELECTION (checkboxes + maestro + contador)
    // ============================================================
    /**
     * Inicializa la gestión de selección de filas mediante checkboxes.
     *
     * - Sincroniza el checkbox maestro con los individuales.
     * - Mantiene el estado "indeterminado" del maestro.
     * - Actualiza un contador opcional con el número de seleccionados.
     * - Respeta el filtro rápido (solo cuenta/selecciona filas visibles).
     *
     * Opciones:
     *   - checkboxSelector  (requerido) Selector de los checkboxes individuales.
     *                                  Ej: '.rule-checkbox'
     *   - masterCheckboxId  (opcional)  ID del checkbox maestro ("seleccionar todos").
     *   - counterId         (opcional)  ID del span para el contador.
     *   - rowSelector       (opcional)  Selector de las filas (para respetar el filtro).
     *                                  Ej: 'tbody tr[data-rule-id]'
     *   - onUpdate          (opcional)  Callback (selectedCount, totalCount) => void
     *
     * @param {object} opts
     * @returns {{ refresh: Function, getSelected: Function, getSelectedCount: Function }}
     */
    function initSelection(opts) {
        opts = opts || {};
        const checkboxSelector = opts.checkboxSelector || 'input[type="checkbox"]';
        const masterCheckboxId = opts.masterCheckboxId;
        const counterId = opts.counterId;
        const rowSelector = opts.rowSelector;
        const onUpdate = opts.onUpdate;

        const master = masterCheckboxId ? document.getElementById(masterCheckboxId) : null;
        const counter = counterId ? document.getElementById(counterId) : null;

        function getCheckboxes() {
            return Array.from(document.querySelectorAll(checkboxSelector));
        }

        function getVisibleCheckboxes() {
            const all = getCheckboxes();
            if (!rowSelector) return all;
            return all.filter(cb => {
                const row = cb.closest(rowSelector);
                return row && _isVisible(row);
            });
        }

        function getSelected() {
            return getCheckboxes().filter(cb => cb.checked);
        }

        function getSelectedCount() {
            return getSelected().length;
        }

        function refresh() {
            const all = getCheckboxes();
            const checked = getSelected();
            const visible = getVisibleCheckboxes();
            const visibleChecked = visible.filter(cb => cb.checked);

            if (master) {
                master.checked = all.length > 0 && checked.length === all.length;
                master.indeterminate =
                    checked.length > 0 && checked.length < all.length;
            }

            if (counter) {
                if (checked.length > 0) {
                    counter.textContent =
                        `${checked.length} seleccionada${checked.length === 1 ? '' : 's'}`;
                    counter.className = 'small text-primary fw-bold';
                } else if (counter.dataset.defaultEmpty) {
                    counter.textContent = counter.dataset.defaultEmpty;
                    counter.className = 'small text-muted';
                } else {
                    counter.textContent = '';
                    counter.className = 'small text-muted';
                }
            }

            if (typeof onUpdate === 'function') {
                try { onUpdate(checked.length, all.length, visibleChecked.length, visible.length); }
                catch (e) { console.warn(e); }
            }
        }

        // Toggle maestro: selecciona solo las filas visibles (respeta filtro).
        if (master) {
            master.addEventListener('change', () => {
                const visibles = getVisibleCheckboxes();
                visibles.forEach(cb => { cb.checked = master.checked; });
                refresh();
            });
        }

        // Listeners individuales.
        getCheckboxes().forEach(cb => {
            cb.addEventListener('change', refresh);
        });

        // Estado inicial.
        refresh();

        return {
            refresh,
            getSelected: () => getSelected().map(cb => cb.value),
            getSelectedCount,
        };
    }

    // ============================================================
    // 3. CONFIRM BULK (confirmación de acciones masivas)
    // ============================================================
    /**
     * Muestra una confirmación antes de ejecutar una acción masiva.
     *
     * Opciones:
     *   - checkboxSelector  (requerido) Selector de los checkboxes.
     *   - actionLabel       (opcional)  Texto de la acción (default: "esta acción").
     *   - warning           (opcional)  Si true, muestra advertencia destructiva.
     *   - warningText       (opcional)  Texto adicional de la advertencia.
     *   - noSelectionMsg    (opcional)  Mensaje si no hay selección.
     *
     * @param {object} opts
     * @returns {boolean} true si el usuario confirma (o si no hay selección).
     */
    function confirmBulk(opts) {
        opts = opts || {};
        const checkboxSelector = opts.checkboxSelector || 'input[type="checkbox"]:checked';
        const actionLabel = opts.actionLabel || 'esta acción';
        const warning = opts.warning || false;
        const warningText = opts.warningText || '';
        const noSelectionMsg = opts.noSelectionMsg ||
            'No has seleccionado ningún elemento.\n\nMarca al menos una casilla.';

        const checked = document.querySelectorAll(checkboxSelector);
        const n = checked.length;

        if (n === 0) {
            alert(noSelectionMsg);
            return false;
        }

        let msg = `¿${actionLabel.charAt(0).toUpperCase() + actionLabel.slice(1)} ${n} elemento(s)?`;
        if (warning) {
            msg = `¿${actionLabel.charAt(0).toUpperCase() + actionLabel.slice(1)} ${n} elemento(s)?\n\n`;
            msg += 'Esta acción NO se puede deshacer.';
            if (warningText) msg += '\n' + warningText;
        }
        return confirm(msg);
    }

    // ============================================================
    // 4. TOOLTIPS
    // ============================================================
    /**
     * Inicializa todos los tooltips de Bootstrap presentes en la página.
     * Idempotente: se puede llamar varias veces sin efectos secundarios.
     */
    function initTooltips() {
        if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return;
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            if (!bootstrap.Tooltip.getInstance(el)) {
                new bootstrap.Tooltip(el);
            }
        });
    }

    // ============================================================
    // 5. KEYBOARD SHORTCUTS
    // ============================================================
    /**
     * Inicializa atajos de teclado comunes en listados:
     *   - "/"    → enfoca el input de búsqueda.
     *   - "Esc"  → si el foco está en el input, lo limpia y quita el foco.
     *   - "r"    → ejecuta `onReload` si se proporciona.
     *
     * No se dispara si el foco está en un input/textarea/select.
     *
     * Opciones:
     *   - focusSearchId  (opcional)  ID del input a enfocar con "/".
     *   - onReload       (opcional)  Callback para la tecla "r".
     *   - onEscape       (opcional)  Callback adicional para "Esc".
     *
     * @param {object} opts
     */
    function initKeyboardShortcuts(opts) {
        opts = opts || {};
        const focusSearchId = opts.focusSearchId;
        const onReload = opts.onReload;
        const onEscape = opts.onEscape;

        document.addEventListener('keydown', (e) => {
            const typing = _isTypingTarget(e);

            // Esc: si estamos dentro del input de búsqueda, limpiar y salir.
            if (e.key === 'Escape') {
                if (typing && focusSearchId) {
                    const input = document.getElementById(focusSearchId);
                    if (input && e.target === input) {
                        input.value = '';
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.blur();
                        e.preventDefault();
                    }
                }
                if (typeof onEscape === 'function') {
                    try { onEscape(e); } catch (err) { console.warn(err); }
                }
                return;
            }

            if (typing) return;

            // "/" enfoca el buscador.
            if (e.key === '/' && focusSearchId) {
                const input = document.getElementById(focusSearchId);
                if (input) {
                    e.preventDefault();
                    input.focus();
                }
                return;
            }

            // "r" recarga si se proporcionó onReload.
            if ((e.key === 'r' || e.key === 'R') && typeof onReload === 'function') {
                e.preventDefault();
                try { onReload(); } catch (err) { console.warn(err); }
            }
        });
    }

    // ============================================================
    // API PÚBLICA
    // ============================================================
    return {
        initQuickFilter,
        initSelection,
        confirmBulk,
        initTooltips,
        initKeyboardShortcuts,
    };
})();