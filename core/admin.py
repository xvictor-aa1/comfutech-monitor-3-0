# core/admin.py
"""
Admin de la app `core`.

Solo visible para el superadministrador.

Se registran los modelos de verificación de email y recuperación de
contraseña. Los antiguos `SystemConfig` y `EmailConfig` ya no existen
(la configuración vive en `config.toml`).

Para el modelo `User` de Django se usa el `UserAdmin` estándar.
"""
from django.contrib import admin

from .models import (
    EmailVerification,
    PasswordResetAttempt,
    PasswordResetCode,
)


# ============================================================
# VERIFICACIÓN DE EMAIL
# ============================================================
@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "verified", "verified_email", "verified_at",
    )
    list_filter = ("verified", "verified_at")
    search_fields = ("user__username", "user__email", "verified_email")
    raw_id_fields = ("user",)
    readonly_fields = ("token", "token_created_at", "verified_at")
    date_hierarchy = "token_created_at"

    fieldsets = (
        ("Usuario", {
            "fields": ("user",)
        }),
        ("Estado", {
            "fields": ("verified", "verified_at", "verified_email")
        }),
        ("Token", {
            "fields": ("token", "token_created_at"),
            "classes": ("collapse",),
        }),
    )


# ============================================================
# RECUPERACIÓN DE CONTRASEÑA — CÓDIGOS
# ============================================================
@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "code", "created_at", "expires_at", "used",
    )
    list_filter = ("used", "created_at")
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("code", "created_at")
    date_hierarchy = "created_at"


# ============================================================
# RECUPERACIÓN DE CONTRASEÑA — INTENTOS (auditoría)
# ============================================================
@admin.register(PasswordResetAttempt)
class PasswordResetAttemptAdmin(admin.ModelAdmin):
    """Registro de solo lectura (auditoría de intentos)."""

    list_display = ("id", "user", "ip", "successful", "created_at")
    list_filter = ("successful", "created_at")
    search_fields = ("user__username", "user__email", "ip")
    raw_id_fields = ("user",)
    readonly_fields = ("user", "ip", "successful", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        """No se crean intentos manualmente."""
        return False

    def has_change_permission(self, request, obj=None):
        """Solo lectura."""
        return False