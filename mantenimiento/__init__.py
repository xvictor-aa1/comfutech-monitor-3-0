# mantenimiento/__init__.py
"""
App `mantenimiento`: Panel de Mantenimiento del sistema.

Acceso exclusivo para el superadministrador.

Incluye:
  - Backups manuales de la BD (SQL.gz) y configs (.toml en ZIP).
  - Backups automáticos programados (integrados con el monitor).
  - Backups automáticos al iniciar.
  - Retención automática (eliminación de backups antiguos).
"""