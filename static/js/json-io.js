/**
 * json-io.js — Utilidades de lectura/escritura de archivos JSON.
 *
 * Usado por:
 *   - inventario/device_list.html
 *   - inventario/device_model_list.html
 *   - inventario/device_form.html
 *   - inventario/device_model_form.html
 *
 * API pública:
 *   JsonIO.readFile(file, opts)              → Promise<object>
 *   JsonIO.parse(text)                       → object | throws
 *   JsonIO.normalizeToSingle(parsed)         → object | throws
 *   JsonIO.validateRequired(obj, keys)       → { ok, missing }
 *   JsonIO.download(data, filename)          → void (descarga blob)
 *   JsonIO.MAX_FILE_SIZE_MB                  → 5
 *
 * Carga:
 *   <script src="{% static 'js/json-io.js' %}"></script>
 */

window.JsonIO = (function () {
    'use strict';

    const MAX_FILE_SIZE_MB = 5;
    const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

    // ============================================================
    // PARSE
    // ============================================================
    /**
     * Parsea un string JSON, tolerando BOM.
     *
     * @param {string} text
     * @returns {object|Array}
     * @throws {Error} con mensaje legible
     */
    function parse(text) {
        if (typeof text !== 'string') {
            throw new Error('El contenido no es texto.');
        }
        // Tolerar BOM al inicio del archivo.
        const clean = text.replace(/^\uFEFF/, '');
        try {
            return JSON.parse(clean);
        } catch (e) {
            throw new Error(`JSON inválido: ${e.message}`);
        }
    }

    // ============================================================
    // READ FILE
    // ============================================================
    /**
     * Lee un archivo del sistema y devuelve su contenido parseado.
     *
     * Opciones:
     *   - maxSizeMb     (opcional) Tamaño máximo (default: 5 MB).
     *   - allowedExt    (opcional) Array de extensiones permitidas
     *                              (default: ['.json']).
     *
     * @param {File} file
     * @param {object} [opts]
     * @returns {Promise<object|Array>}
     */
    function readFile(file, opts) {
        opts = opts || {};
        const maxSizeMb = opts.maxSizeMb || MAX_FILE_SIZE_MB;
        const maxSizeBytes = maxSizeMb * 1024 * 1024;
        const allowedExt = opts.allowedExt || ['.json'];

        return new Promise((resolve, reject) => {
            if (!file) {
                reject(new Error('No se seleccionó ningún archivo.'));
                return;
            }

            if (file.size > maxSizeBytes) {
                const kb = Math.round(file.size / 1024);
                reject(new Error(
                    `El archivo es demasiado grande (${kb} KB). ` +
                    `Máximo ${maxSizeMb} MB.`
                ));
                return;
            }

            const nameLower = (file.name || '').toLowerCase();
            const hasAllowedExt = allowedExt.some(ext =>
                nameLower.endsWith(ext.toLowerCase())
            );
            if (!hasAllowedExt) {
                reject(new Error(
                    `Extensión no permitida. Se esperaba: ${allowedExt.join(', ')}.`
                ));
                return;
            }

            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const parsed = parse(e.target.result);
                    resolve(parsed);
                } catch (err) {
                    reject(err);
                }
            };
            reader.onerror = () => {
                reject(new Error('No se pudo leer el archivo.'));
            };
            reader.readAsText(file, 'utf-8');
        });
    }

    // ============================================================
    // NORMALIZE
    // ============================================================
    /**
     * Normaliza el JSON a un único objeto.
     *
     * Acepta:
     *   - Un objeto directo → lo devuelve tal cual.
     *   - Un array de 1 elemento → devuelve ese elemento.
     *
     * Rechaza:
     *   - Arrays vacíos.
     *   - Arrays con más de 1 elemento (mensaje indicando importación masiva).
     *   - Tipos no objeto (string, number, null).
     *
     * Opciones:
     *   - entityLabel (opcional) Texto de la entidad, ej: "modelo" o "equipo".
     *                            Se usa en el mensaje de error.
     *
     * @param {*} parsed
     * @param {object} [opts]
     * @returns {object}
     * @throws {Error}
     */
    function normalizeToSingle(parsed, opts) {
        opts = opts || {};
        const entityLabel = opts.entityLabel || 'elemento';

        if (parsed === null || parsed === undefined) {
            throw new Error('El archivo está vacío.');
        }

        if (Array.isArray(parsed)) {
            if (parsed.length === 0) {
                throw new Error('El archivo está vacío.');
            }
            if (parsed.length > 1) {
                throw new Error(
                    `Este formulario solo acepta UN ${entityLabel}. ` +
                    `El archivo contiene ${parsed.length}. ` +
                    `Para importación masiva usa la lista.`
                );
            }
            const item = parsed[0];
            if (typeof item !== 'object' || item === null || Array.isArray(item)) {
                throw new Error(`El elemento del array no es un objeto ${entityLabel}.`);
            }
            return item;
        }

        if (typeof parsed !== 'object') {
            throw new Error(
                `El JSON debe ser un objeto ${entityLabel}, no ${typeof parsed}.`
            );
        }

        return parsed;
    }

    // ============================================================
    // VALIDATE REQUIRED
    // ============================================================
    /**
     * Verifica que un objeto tenga los campos requeridos (string no vacío).
     *
     * @param {object} obj
     * @param {string[]} keys
     * @returns {{ok: boolean, missing: string[]}}
     */
    function validateRequired(obj, keys) {
        const missing = [];
        if (!obj || typeof obj !== 'object') {
            return { ok: false, missing: keys.slice() };
        }
        keys.forEach(k => {
            const v = obj[k];
            if (v === undefined || v === null || String(v).trim() === '') {
                missing.push(k);
            }
        });
        return { ok: missing.length === 0, missing };
    }

    // ============================================================
    // DOWNLOAD
    // ============================================================
    /**
     * Descarga un objeto/array como archivo JSON.
     *
     * @param {object|Array} data
     * @param {string} filename  Ej: "equipos.json"
     * @param {object} [opts]
     *   - indent  (default: 2) — sangría del JSON.
     */
    function download(data, filename, opts) {
        opts = opts || {};
        const indent = opts.indent !== undefined ? opts.indent : 2;
        const json = JSON.stringify(data, null, indent);

        const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'data.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        // Liberar el blob después de un pequeño delay.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    // ============================================================
    // API PÚBLICA
    // ============================================================
    return {
        MAX_FILE_SIZE_MB,
        parse,
        readFile,
        normalizeToSingle,
        validateRequired,
        download,
    };
})();