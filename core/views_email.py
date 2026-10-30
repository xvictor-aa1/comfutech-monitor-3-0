# core/views_email.py
"""Vistas para verificación de email."""
from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import require_admin_or_super
from core.email_utils import send_verification_email
from core.models import EmailVerification


@require_admin_or_super()
def user_send_verification(request, user_id):
    """
    Envía (o reenvía) el email de verificación al usuario.
    Solo permite enviar si el email no está ya verificado.
    """
    if request.method != "POST":
        return redirect("core:user_edit", user_id=user_id)

    target = get_object_or_404(User, pk=user_id)

    if not target.email:
        messages.error(request, "El usuario no tiene email configurado.")
        return redirect("core:user_list")

    # Verificar que no haya otro usuario con el mismo email
    if User.objects.filter(email__iexact=target.email).exclude(pk=user_id).exists():
        messages.error(
            request,
            "El email ya está registrado con otro usuario."
        )
        return redirect("core:user_edit", user_id=user_id)

    verification = EmailVerification.get_or_create_for(target)

    # Si ya está verificado y coincide, no reenviar
    if (verification.verified
            and verification.verified_email
            and verification.verified_email.lower() == target.email.lower()):
        messages.info(request, f"El correo {target.email} ya está verificado.")
        return redirect("core:user_list")

    # Regenerar token y enviar
    token = verification.regenerate_token()
    ok, error = send_verification_email(request, target, token)

    if ok:
        messages.success(
            request,
            f"✅ Enlace de verificación enviado a {target.email}."
        )
    else:
        messages.error(request, f"❌ No se pudo enviar el email: {error}")

    return redirect("core:user_list")


def verify_email(request, token):
    """
    Endpoint público que valida el email usando el token del enlace.
    No requiere autenticación.
    """
    try:
        verification = EmailVerification.objects.select_related("user").get(
            token=token
        )
    except EmailVerification.DoesNotExist:
        return render(request, "core/email_verify_result.html", {
            "success": False,
            "title": "Enlace inválido",
            "message": (
                "El enlace de verificación no es válido o ya fue usado. "
                "Contacta al administrador."
            ),
        })

    user = verification.user

    # ¿Ya estaba verificado?
    if (verification.verified
            and verification.verified_email
            and verification.verified_email.lower() == (user.email or "").lower()):
        return render(request, "core/email_verify_result.html", {
            "success": True,
            "already": True,
            "title": "Correo ya verificado",
            "message": (
                f"El correo {verification.verified_email} ya estaba verificado."
            ),
            "target_user": user,
        })

    # ¿Token expirado?
    if not verification.is_token_valid(max_age_hours=48):
        return render(request, "core/email_verify_result.html", {
            "success": False,
            "title": "Enlace expirado",
            "message": (
                "El enlace expiró (más de 48 horas). "
                "Solicita uno nuevo al administrador."
            ),
        })

    if not user.email:
        return render(request, "core/email_verify_result.html", {
            "success": False,
            "title": "Sin correo asignado",
            "message": "La cuenta no tiene un correo asignado.",
        })

    # Marcar como verificado
    verification.mark_verified(user.email)

    return render(request, "core/email_verify_result.html", {
        "success": True,
        "title": "¡Correo verificado!",
        "message": (
            f"El correo {user.email} fue verificado correctamente."
        ),
        "target_user": user,
    })