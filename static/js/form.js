/**
 * forms.js — Utilidades para formularios.
 *
 * Incluye:
 *   - togglePassword(inputId, btn): mostrar/ocultar contraseña.
 *   - PasswordStrength: evaluación de fuerza de contraseña.
 *   - warnOnUnsavedChanges(form): advertencia al salir con cambios.
 *
 * Uso:
 *   <script src="{% static 'js/forms.js' %}"></script>
 *
 *   Forms.togglePassword('id_password1', this);
 *   Forms.initPasswordStrength('id_password1', 'id_password2');
 *   Forms.warnOnUnsavedChanges(document.getElementById('mi-form'));
 *
 * Convención de IDs que usa `initPasswordStrength`:
 *   - strength-container: contenedor del indicador (display:none inicial)
 *   - strength-bar:       progress-bar interno
 *   - strength-label:     <small> con la etiqueta de fuerza
 *   - match-feedback:     <div> con el mensaje de coincidencia
 *
 *   Si en el template los IDs difieren, se pueden pasar como opciones.
 */

window.Forms = (function () {
    'use strict';

    // ============================================================
    // TOGGLE PASSWORD
    // ============================================================
    /**
     * Muestra u oculta el valor de un input de contraseña y
     * cambia el icono del botón asociado (bi-eye ↔ bi-eye-slash).
     *
     * @param {string} inputId  ID del input (ej. "id_password1")
     * @param {HTMLElement} btn Botón que dispara el toggle (opcional)
     */
    function togglePassword(inputId, btn) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const icon = btn ? btn.querySelector('i') : null;
        if (input.type === 'password') {
            input.type = 'text';
            if (icon) {
                icon.classList.remove('bi-eye');
                icon.classList.add('bi-eye-slash');
            }
        } else {
            input.type = 'password';
            if (icon) {
                icon.classList.remove('bi-eye-slash');
                icon.classList.add('bi-eye');
            }
        }
    }

    // ============================================================
    // PASSWORD STRENGTH
    // ============================================================
    /**
     * Calcula un score de 0 a 5 según la complejidad de la contraseña.
     *
     * @param {string} password
     * @returns {number} 0..5
     */
    function checkStrength(password) {
        let score = 0;
        if (!password) return 0;
        if (password.length >= 8)             score += 1;
        if (/[a-z]/.test(password))           score += 1;
        if (/[A-Z]/.test(password))           score += 1;
        if (/\d/.test(password))              score += 1;
        if (/[^A-Za-z0-9]/.test(password))    score += 1;
        if (password.length >= 12)            score += 1;
        return Math.min(score, 5);
    }

    /**
     * Devuelve el nivel visual (color, ancho, texto, clase) para una
     * contraseña dada. Si la contraseña está vacía devuelve null.
     */
    function _strengthLevel(password) {
        if (!password) return null;
        const score = checkStrength(password);
        if (password.length < 8)  return { color: 'bg-danger',  width: 20,  text: 'Muy corta',  textCls: 'danger'  };
        if (score <= 2)           return { color: 'bg-danger',  width: 30,  text: 'Débil',      textCls: 'danger'  };
        if (score === 3)          return { color: 'bg-warning', width: 55,  text: 'Aceptable',  textCls: 'warning' };
        if (score === 4)          return { color: 'bg-info',    width: 75,  text: 'Buena',      textCls: 'info'    };
        return                          { color: 'bg-success', width: 100, text: 'Excelente',  textCls: 'success' };
    }

    /**
     * Actualiza los elementos visuales del indicador de fuerza.
     * Los IDs por defecto se pueden sobrescribir con `ids`.
     *
     * @param {HTMLInputElement} input
     * @param {object} [ids]
     *   - containerId (default "strength-container")
     *   - barId       (default "strength-bar")
     *   - labelId     (default "strength-label")
     */
    function updateStrength(input, ids) {
        ids = ids || {};
        const containerId = ids.containerId || 'strength-container';
        const barId       = ids.barId       || 'strength-bar';
        const labelId     = ids.labelId     || 'strength-label';

        const container = document.getElementById(containerId);
        const bar       = document.getElementById(barId);
        const label     = document.getElementById(labelId);
        if (!container || !bar || !label) return;

        const password = input.value;
        if (!password) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'block';

        const level = _strengthLevel(password);
        bar.className   = 'progress-bar ' + level.color;
        bar.style.width = level.width + '%';
        label.textContent = level.text;
        label.className   = 'fw-bold text-' + level.textCls;
    }

    /**
     * Compara dos inputs de contraseña y actualiza el feedback visual.
     *
     * @param {HTMLInputElement} p1
     * @param {HTMLInputElement} p2
     * @param {string} [feedbackId="match-feedback"]
     */
    function checkMatch(p1, p2, feedbackId) {
        feedbackId = feedbackId || 'match-feedback';
        const feedback = document.getElementById(feedbackId);
        if (!feedback) return;

        if (!p2.value) {
            feedback.textContent = '';
            return;
        }

        if (p1.value === p2.value) {
            feedback.innerHTML =
                '<i class="bi bi-check-circle-fill text-success"></i> Las contraseñas coinciden.';
            feedback.className = 'form-text text-success';
        } else {
            feedback.innerHTML =
                '<i class="bi bi-x-circle-fill text-danger"></i> Las contraseñas no coinciden.';
            feedback.className = 'form-text text-danger';
        }
    }

    /**
     * Inicializa los listeners de strength + match para un par de inputs.
     * Es la forma recomendada: una sola llamada en el DOMContentLoaded.
     *
     * @param {string} p1Id  ID del primer input (contraseña)
     * @param {string} p2Id  ID del segundo input (confirmación)
     * @param {object} [ids] Ver `updateStrength`
     */
    function initPasswordStrength(p1Id, p2Id, ids) {
        const p1 = document.getElementById(p1Id);
        const p2 = document.getElementById(p2Id);
        if (!p1 || !p2) return;

        p1.addEventListener('input', () => {
            updateStrength(p1, ids);
            checkMatch(p1, p2, ids && ids.feedbackId);
        });
        p2.addEventListener('input', () => {
            checkMatch(p1, p2, ids && ids.feedbackId);
        });
    }

    // ============================================================
    // WARN ON UNSAVED CHANGES
    // ============================================================
    /**
     * Registra `beforeunload` para advertir si hay cambios sin guardar.
     * Se desactiva automáticamente al enviar el formulario.
     *
     * @param {HTMLFormElement} form
     */
    function warnOnUnsavedChanges(form) {
        if (!form) return;
        let dirty = false;
        form.addEventListener('input',  () => { dirty = true; });
        form.addEventListener('change', () => { dirty = true; });
        form.addEventListener('submit', () => { dirty = false; });
        window.addEventListener('beforeunload', (e) => {
            if (dirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    }

    return {
        togglePassword,
        checkStrength,
        updateStrength,
        checkMatch,
        initPasswordStrength,
        warnOnUnsavedChanges,
    };
})();