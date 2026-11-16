/**
 * theme.js — Theme switcher (claro / oscuro / automático).
 *
 * Usado por: base.html (siempre cargado).
 *
 * API pública (expuesta en `window`):
 *   - setTheme(theme)     'light' | 'dark' | 'auto' — aplica y persiste.
 *   - applyTheme(theme)   'light' | 'dark' | 'auto' — aplica sin persistir.
 *
 * Persistencia:
 *   - Guarda la elección del usuario en `localStorage['cf-theme']`.
 *   - El tema se aplica ANTES del render inicial por un script inline
 *     en `<head>` (para evitar el "flash" de tema claro). Ese preload
 *     NO se puede mover a este archivo porque se ejecuta antes de que
 *     el CSS cargue.
 *
 * Este módulo se encarga de:
 *   1. Sincronizar los iconos/checks del dropdown con el tema actual.
 *   2. Detectar cambios del sistema operativo (si `auto` está activo).
 *   3. Aplicar el tema guardado al `DOMContentLoaded`.
 *
 * Se carga al final del body (no en `<head>`) porque necesita el DOM
 * del dropdown de tema para reflejar el check del tema actual.
 */
(function () {
    'use strict';

    /**
     * Aplica un tema SIN persistirlo.
     *
     * Actualiza el atributo `data-bs-theme` del `<html>` y los iconos
     * + checks del dropdown de tema del sidebar.
     *
     * @param {string} theme — 'light' | 'dark' | 'auto'
     */
    function applyTheme(theme) {
        let effective = theme;
        if (theme === 'auto') {
            effective = window.matchMedia('(prefers-color-scheme: dark)').matches
                ? 'dark' : 'light';
        }
        document.documentElement.setAttribute('data-bs-theme', effective);

        // Actualizar icono y label del botón del dropdown.
        const icon = document.getElementById('theme-icon');
        const label = document.getElementById('theme-label');
        if (icon) {
            icon.className = 'bi';
            if (theme === 'light') icon.classList.add('bi-sun-fill');
            else if (theme === 'dark') icon.classList.add('bi-moon-stars-fill');
            else icon.classList.add('bi-circle-half');
        }
        if (label) {
            label.textContent = {
                'light': 'Claro',
                'dark': 'Oscuro',
                'auto': 'Automático',
            }[theme] || 'Tema';
        }

        // Mostrar el check solo en el ítem activo del dropdown.
        document.querySelectorAll('.dropdown-item[data-theme]').forEach(btn => {
            const check = btn.querySelector('.bi-check2');
            if (!check) return;
            check.style.display = (btn.dataset.theme === theme)
                ? 'inline-block' : 'none';
        });
    }

    /**
     * Aplica un tema Y lo persiste en `localStorage`.
     *
     * @param {string} theme — 'light' | 'dark' | 'auto'
     */
    function setTheme(theme) {
        try { localStorage.setItem('cf-theme', theme); } catch (e) {}
        applyTheme(theme);
    }

    // Escuchar cambios del sistema operativo.
    // Solo aplica si el usuario tiene `auto` seleccionado.
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            let stored = 'auto';
            try { stored = localStorage.getItem('cf-theme') || 'auto'; } catch (e) {}
            if (stored === 'auto') applyTheme('auto');
        });
    }

    // Aplicar el tema guardado al cargar la página.
    document.addEventListener('DOMContentLoaded', () => {
        let stored = 'auto';
        try { stored = localStorage.getItem('cf-theme') || 'auto'; } catch (e) {}
        applyTheme(stored);
    });

    // API pública (para `onclick="setTheme(...)"` del dropdown).
    window.applyTheme = applyTheme;
    window.setTheme = setTheme;
})();