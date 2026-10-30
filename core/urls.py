# core/urls.py
"""Rutas URL de la app `core`."""
from django.urls import path

from . import (
    views,
    views_users,
    views_settings,
    views_email,
    views_password_reset,
    views_auth,
)

app_name = "core"

urlpatterns = [
    path("setup/", views_auth.superadmin_setup, name="superadmin_setup"),
    path("", views.dashboard, name="dashboard"),

    # Usuarios
    path("usuarios/", views_users.user_list, name="user_list"),
    path("usuarios/nuevo/", views_users.user_create, name="user_create"),
    path("usuarios/<int:user_id>/editar/", views_users.user_edit, name="user_edit"),
    path("usuarios/<int:user_id>/password/", views_users.user_change_password,
         name="user_change_password"),
    path("usuarios/<int:user_id>/eliminar/", views_users.user_delete, name="user_delete"),
    path("perfil/", views_users.profile, name="profile"),

    # Verificación de email
    path("usuarios/<int:user_id>/enviar-verificacion/",
         views_email.user_send_verification, name="user_send_verification"),
    path("verificar-email/<uuid:token>/",
         views_email.verify_email, name="verify_email"),

    # Configuración
    path("configuracion/", views_settings.system_settings, name="system_settings"),
    path("configuracion/test-telegram/", views_settings.test_telegram, name="test_telegram"),
    path("configuracion/test-influx/", views_settings.test_influx, name="test_influx"),
    path("configuracion/test-grafana/", views_settings.test_grafana, name="test_grafana"),
    path("configuracion/test-email/", views_settings.test_email, name="test_email"),

    # Recuperación de contraseña
    path("password-reset/", views_password_reset.password_reset_request, name="password_reset_request"),
    path("password-reset/verify/", views_password_reset.password_reset_verify, name="password_reset_verify"),
    path("password-reset/new-password/", views_password_reset.password_reset_new_password, name="password_reset_new_password"),

    # API: alertas nuevas (toasts del dashboard)
    path("api/recent-alerts/", views.recent_alerts_api, name="recent_alerts_api"),
]