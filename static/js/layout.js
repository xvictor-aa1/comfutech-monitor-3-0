/**
 * layout.js — Comportamiento general de la UI (sidebar + alerts).
 *
 * Usado por: base.html (siempre cargado).
 *
 * Responsabilidades:
 *   - Sidebar colapsable / expandible (desktop).
 *   - Drawer móvil (hamburguesa + overlay).
 *   - Restauración del estado del sidebar desde localStorage.
 *   - Cierre del drawer al hacer clic en un enlace.
 *   - Auto-cierre de alerts de Bootstrap a los 6 segundos.
 *
 * Sidebar:
 *   - Colapsado: 60px (solo iconos centrados).
 *   - Expandido: 220px (iconos + texto + chevron).
 *   - En desktop, expandir/colapsar se hace con el logo del brand.
 *   - En móvil, la hamburguesa abre/cierra un drawer lateral.
 *
 * El estado expandido del sidebar se persiste en
 * `localStorage['cf-sidebar-expanded']` ('1' = expandido).
 *
 * NO expone API pública. Los click handlers se enganchan en el IIFE
 * al cargarse el DOM.
 */
(function () {
    'use strict';

    // ============================================================
    // SIDEBAR
    // ============================================================
    /**
     * Inicializa todos los handlers del sidebar:
     *   - Click en el brand (expandir/colapsar en desktop, drawer en móvil).
     *   - Click en los botones con `data-main-url` cuando está colapsado.
     *   - Restaurar el estado desde localStorage.
     *   - Hamburguesa + overlay en móvil.
     *   - Cierre del drawer al hacer click en un enlace.
     *   - Reajustar al cambiar de tamaño.
     */
    function initSidebar() {
        const sidebar = document.getElementById('cf-sidebar');
        const brand = document.getElementById('cf-sidebar-brand');
        const overlay = document.getElementById('cf-overlay');
        const hamburger = document.getElementById('cf-hamburger');
        if (!sidebar) return;

        const isMobile = () => window.matchMedia('(max-width: 991.98px)').matches;

        // ---- Brand: click expande/colapsa (desktop) o abre/cierra drawer (móvil)
        if (brand) {
            brand.addEventListener('click', (e) => {
                e.preventDefault();
                if (isMobile()) {
                    sidebar.classList.toggle('mobile-open');
                    document.body.classList.toggle('cf-sidebar-mobile-open');
                    if (overlay) overlay.classList.toggle('show');
                } else {
                    sidebar.classList.toggle('expanded');
                    try {
                        localStorage.setItem(
                            'cf-sidebar-expanded',
                            sidebar.classList.contains('expanded') ? '1' : '0'
                        );
                    } catch (e) {}
                }
            });
        }

        // ---- En modo colapsado (solo desktop), los botones con submenú
        // ---- navegan directamente a su apartado principal, sin expandir
        // ---- el sidebar. El sidebar solo se expande/colapsa con el logo.
        document.querySelectorAll('.cf-sidebar-nav .cf-sidebar-item[data-main-url]').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!isMobile() && !sidebar.classList.contains('expanded')) {
                    e.preventDefault();
                    e.stopImmediatePropagation();  // evita que Bootstrap abra el collapse
                    window.location.href = item.dataset.mainUrl;
                }
            }, true);  // capture phase: corre antes que Bootstrap
        });

        // ---- Restaurar estado expandido en desktop
        if (!isMobile()) {
            try {
                if (localStorage.getItem('cf-sidebar-expanded') === '1') {
                    sidebar.classList.add('expanded');
                }
            } catch (e) {}
        }

        // ---- Hamburguesa (móvil)
        if (hamburger) {
            hamburger.addEventListener('click', () => {
                sidebar.classList.toggle('mobile-open');
                document.body.classList.toggle('cf-sidebar-mobile-open');
                if (overlay) overlay.classList.toggle('show');
            });
        }

        // ---- Overlay cierra el drawer
        if (overlay) {
            overlay.addEventListener('click', () => {
                sidebar.classList.remove('mobile-open');
                document.body.classList.remove('cf-sidebar-mobile-open');
                overlay.classList.remove('show');
            });
        }

        // ---- Cerrar drawer al hacer clic en un enlace
        sidebar.querySelectorAll('a[href]:not([href="#"])').forEach(link => {
            link.addEventListener('click', () => {
                if (isMobile()) {
                    sidebar.classList.remove('mobile-open');
                    document.body.classList.remove('cf-sidebar-mobile-open');
                    if (overlay) overlay.classList.remove('show');
                }
            });
        });

        // ---- Ajustes al cambiar de tamaño
        const handleResize = () => {
            if (!isMobile()) {
                sidebar.classList.remove('mobile-open');
                document.body.classList.remove('cf-sidebar-mobile-open');
                if (overlay) overlay.classList.remove('show');
                try {
                    if (localStorage.getItem('cf-sidebar-expanded') === '1') {
                        sidebar.classList.add('expanded');
                    }
                } catch (e) {}
            }
        };
        window.addEventListener('resize', handleResize);
    }

    // ============================================================
    // AUTO-CIERRE DE ALERTS
    // ============================================================
    /**
     * Cierra automáticamente los alerts dismissible a los 6 segundos.
     *
     * Se aplica a los mensajes de Django (`{{ messages }}`) y a cualquier
     * alert que tenga la clase `alert-dismissible`. Usa la API de
     * Bootstrap para cerrarlo con la animación nativa.
     */
    function initAutoCloseAlerts() {
        document.querySelectorAll('.alert.alert-dismissible').forEach(el => {
            setTimeout(() => {
                try {
                    const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
                    bsAlert.close();
                } catch (e) {}
            }, 6000);
        });
    }

    // ============================================================
    // INIT
    // ============================================================
    document.addEventListener('DOMContentLoaded', () => {
        initSidebar();
        initAutoCloseAlerts();
    });
})();