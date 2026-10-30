# core/views_password_reset.py
"""
Flujo de recuperación de contraseña mediante código temporal:
  1. /password-reset/              → pedir usuario/email
  2. /password-reset/verify/       → verificar código de 8 dígitos
  3. /password-reset/new-password/ → establecer nueva contraseña

El código es válido por 5 minutos. Además, se exige que el email del
usuario esté verificado.
"""
import logging

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from django.shortcuts import render, redirect

from .models import EmailVerification, PasswordResetCode, PasswordResetAttempt
from .email_utils import send_password_reset_email

log = logging.getLogger(__name__)


def _get_client_ip(request) -> str:
    """Devuelve la IP del cliente."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


# ============================================================
# PASO 1: Solicitar código
# ============================================================
def password_reset_request(request):
    """
    Solicita un código de recuperación.

    Requisitos:
      - El usuario debe existir y estar activo.
      - El email del usuario debe estar verificado.
      - No debe superar el límite de intentos fallidos.
    """
    if request.method == "POST":
        identifier = request.POST.get("identifier", "").strip()

        if not identifier:
            messages.error(request, "Debes indicar tu usuario o email.")
            return render(request, "core/password_reset_request.html")

        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier),
            is_active=True,
        ).first()

        if not user:
            messages.error(
                request,
                "No se encontró una cuenta activa con esos datos."
            )
            return render(request, "core/password_reset_request.html")

        if not user.email:
            messages.error(
                request,
                "Esta cuenta no tiene email registrado."
            )
            return render(request, "core/password_reset_request.html")

        # Verificar que el email esté VALIDADO
        try:
            verification = EmailVerification.objects.get(user=user)
            email_verified = (
                verification.verified
                and verification.verified_email
                and verification.verified_email.lower() == user.email.lower()
            )
        except EmailVerification.DoesNotExist:
            email_verified = False

        if not email_verified:
            messages.error(
                request,
                "El correo electrónico de esta cuenta no está verificado. "
                "Contacta al administrador del sistema."
            )
            return render(request, "core/password_reset_request.html")

        # Anti-fuerza-bruta
        if PasswordResetAttempt.recent_failed_count(user, minutes=15) >= 5:
            messages.error(
                request,
                "Se han superado los intentos permitidos. "
                "Espera 15 minutos."
            )
            return render(request, "core/password_reset_request.html")

        # Generar y enviar código
        reset_code = PasswordResetCode.generate_for(user, minutes=5)
        ok, error = send_password_reset_email(request, user, reset_code.code)

        if not ok:
            messages.error(
                request,
                "No se pudo enviar el email. Contacta al administrador."
            )
            return render(request, "core/password_reset_request.html")

        request.session["password_reset_user_id"] = user.id
        request.session["password_reset_code_id"] = reset_code.id

        messages.success(
            request,
            f"Se envió un código de 8 dígitos a {user.email}. "
            f"Válido por 5 minutos."
        )
        return redirect("core:password_reset_verify")

    return render(request, "core/password_reset_request.html")


# ============================================================
# PASO 2: Verificar código
# ============================================================
def password_reset_verify(request):
    """Verifica el código de 8 dígitos."""
    user_id = request.session.get("password_reset_user_id")
    code_id = request.session.get("password_reset_code_id")

    if not user_id or not code_id:
        messages.error(request, "Sesión inválida. Comienza de nuevo.")
        return redirect("core:password_reset_request")

    try:
        user = User.objects.get(pk=user_id)
        reset_code = PasswordResetCode.objects.get(pk=code_id, user=user)
    except (User.DoesNotExist, PasswordResetCode.DoesNotExist):
        messages.error(request, "Sesión inválida.")
        request.session.pop("password_reset_user_id", None)
        request.session.pop("password_reset_code_id", None)
        return redirect("core:password_reset_request")

    if not reset_code.is_valid():
        messages.error(request, "El código ha expirado. Solicita uno nuevo.")
        return redirect("core:password_reset_request")

    if request.method == "POST":
        entered = request.POST.get("code", "").strip()
        ip = _get_client_ip(request)

        if entered != reset_code.code:
            PasswordResetAttempt.log(user, ip, success=False)
            remaining = reset_code.seconds_remaining()

            if remaining <= 0:
                messages.error(request, "El código ha expirado.")
                return redirect("core:password_reset_request")

            messages.error(request, "Código incorrecto.")
            return render(request, "core/password_reset_verify.html", {
                "user_email": user.email,
                "seconds_remaining": remaining,
            })

        # Código correcto
        reset_code.used = True
        reset_code.save(update_fields=["used"])
        PasswordResetAttempt.log(user, ip, success=True)

        request.session["password_reset_verified"] = True
        request.session["password_reset_user_id_verified"] = user.id
        request.session.pop("password_reset_user_id", None)
        request.session.pop("password_reset_code_id", None)

        return redirect("core:password_reset_new_password")

    return render(request, "core/password_reset_verify.html", {
        "user_email": user.email,
        "seconds_remaining": reset_code.seconds_remaining(),
    })


# ============================================================
# PASO 3: Nueva contraseña
# ============================================================
def password_reset_new_password(request):
    """Establece la nueva contraseña tras verificar el código."""
    verified = request.session.get("password_reset_verified")
    user_id = request.session.get("password_reset_user_id_verified")

    if not verified or not user_id:
        messages.error(request, "Debes verificar el código primero.")
        return redirect("core:password_reset_request")

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        messages.error(request, "Usuario no encontrado.")
        return redirect("core:password_reset_request")

    if request.method == "POST":
        p1 = request.POST.get("password1", "")
        p2 = request.POST.get("password2", "")

        errors = []
        if len(p1) < 8:
            errors.append("La contraseña debe tener al menos 8 caracteres.")
        elif len(p1) > 16:
            errors.append("La contraseña no puede superar los 16 caracteres.")
        if p1 != p2:
            errors.append("Las contraseñas no coinciden.")

        if not errors:
            try:
                validate_password(p1, user)
            except ValidationError as e:
                errors.extend(e.messages)

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "core/password_reset_new_password.html", {
                "target_user": user,
            })

        user.set_password(p1)
        user.save()

        for key in (
            "password_reset_user_id", "password_reset_code_id",
            "password_reset_verified", "password_reset_user_id_verified",
        ):
            request.session.pop(key, None)

        messages.success(
            request,
            "Contraseña actualizada. Ya puedes iniciar sesión."
        )
        return redirect("login")

    return render(request, "core/password_reset_new_password.html", {
        "target_user": user,
    })