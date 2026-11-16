/**
 * help.js — Sistema de ayuda global (modal F1).
 *
 * Usado por: base.html (siempre cargado).
 *
 * Cada página registra su contenido de ayuda con
 * `registerHelpContent({...})` en su `{% block extra_js %}`. Este
 * módulo se encarga de:
 *   - Abrir el modal de ayuda con el contenido registrado.
 *   - Mostrar un fallback si la página no registró contenido.
 *   - Renderizar las secciones (heading + body + list opcional).
 *   - Escuchar el atajo F1 / Shift+? para abrir la ayuda.
 *
 * API pública (expuesta en `window`):
 *   - registerHelpContent(content)   Registra el contenido de la página.
 *   - openHelpModal()                Abre el modal con el contenido actual.
 *
 * Formato del `content`:
 *   {
 *     title: "Título del modal",
 *     sections: [
 *       {
 *         heading: "Título de la sección",
 *         body: "<p>HTML del cuerpo</p>",
 *         list: ["item1", "item2"]   // opcional
 *       },
 *       ...
 *     ]
 *   }
 *
 * El atajo F1/Shift+? NO se dispara si el foco está en un
 * input / textarea / select, para no interferir con la escritura.
 */
(function () {
    'use strict';

    // Contenido registrado por la página actual.
    // Se inicia como `null` para que `openHelpModal` muestre el fallback
    // si la página no llamó a `registerHelpContent`.
    window._helpContent = null;

    /**
     * Registra el contenido de ayuda de la página actual.
     *
     * Cada página llama a esto en su bloque `extra_js`, después de que
     * este archivo se haya cargado (lo cual está garantizado porque
     * `help.js` se carga en `base.html` antes de `{% block extra_js %}`).
     *
     * @param {object} content — { title, sections: [{heading, body, list}] }
     */
    function registerHelpContent(content) {
        window._helpContent = content;
    }

    /**
     * Escapa HTML básico para insertar texto dinámico de forma segura.
     *
     * Se usa en los `heading` de las secciones, que se insertan con
     * `innerHTML`. Los `body` y los `list` NO se escapan porque se
     * asume que el contenido es controlado por el desarrollador
     * (contiene HTML con iconos, badges, etc.).
     *
     * @param {string} s
     * @returns {string}
     */
    function escapeHtmlHelp(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /**
     * Abre el modal de ayuda con el contenido registrado para la
     * página actual. Si no hay contenido, muestra un fallback
     * invitando al usuario a navegar a otra sección.
     */
    function openHelpModal() {
        const titleEl = document.getElementById('help-modal-title');
        const bodyEl = document.getElementById('help-modal-body');
        if (!titleEl || !bodyEl) return;

        const content = window._helpContent;

        if (!content) {
            // Fallback: la página no registró contenido.
            titleEl.textContent = 'Ayuda';
            bodyEl.innerHTML = `
                <div class="alert alert-info mb-0">
                    <i class="bi bi-info-circle"></i>
                    <strong>No hay contenido de ayuda específico para esta página.</strong>
                    <p class="mb-0 mt-2 small">
                        Navega a Dashboard, Equipos, Alertas, Reglas o Monitor
                        para ver la ayuda detallada de cada sección.
                    </p>
                </div>
            `;
        } else {
            // Renderizar secciones.
            titleEl.textContent = content.title || 'Ayuda';
            const sections = (content.sections || []).map(section => {
                let html = `<div class="mb-4 pb-3 border-bottom">
                    <h6 class="text-primary mb-2">
                        <i class="bi bi-bookmark-fill"></i>
                        ${escapeHtmlHelp(section.heading || '')}
                    </h6>
                    <div class="small text-body">${section.body || ''}</div>`;

                if (section.list && section.list.length > 0) {
                    html += `<ul class="small mt-2 mb-0">
                        ${section.list.map(item => `<li>${item}</li>`).join('')}
                    </ul>`;
                }
                html += `</div>`;
                return html;
            }).join('');

            bodyEl.innerHTML = sections;
        }

        // Mostrar el modal (Bootstrap).
        const modal = new bootstrap.Modal(document.getElementById('helpModal'));
        modal.show();
    }

    // Atajo de teclado: F1 o Shift+? abre la ayuda.
    // No se dispara si el foco está en un input/textarea/select.
    document.addEventListener('keydown', (e) => {
        const tag = (e.target.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

        if (e.key === 'F1' || (e.shiftKey && e.key === '?')) {
            e.preventDefault();
            openHelpModal();
        }
    });

    // API pública (para `onclick="openHelpModal()"` del sidebar y topbar).
    window.registerHelpContent = registerHelpContent;
    window.openHelpModal = openHelpModal;
})();