# core/signals.py
"""
Signals de la app `core`.

Históricamente este módulo invalidaba el caché de `runtime_config`
cuando se guardaban `SystemConfig` y `EmailConfig`. Tras la migración
a `config.toml`, esos modelos ya no existen.

La configuración se recarga automáticamente por mtime
(`core.config_ini.reload_if_changed()`), por lo que ya no se
necesitan signals.

Módulo conservado para no romper `core/apps.py` (que lo importa en
`ready()`), pero está intencionalmente vacío.
"""