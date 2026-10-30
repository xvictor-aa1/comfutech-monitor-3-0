# core/__init__.py
"""
App `core`: contiene la lógica común del sistema.

Incluye:
  - Autenticación personalizada (login + setup inicial).
  - Gestión de usuarios.
  - Gestión de roles.
  - Configuración del sistema.
  - Recuperación de contraseña.
  - Verificación de email.
  - Dashboard principal.
  - Utilidades (sorting, decoradores, runtime config).
"""
default_app_config = "core.apps.CoreConfig"