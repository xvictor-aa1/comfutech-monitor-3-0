# core/email_utils.py
"""Utilidades para envío de emails transaccionales."""
import logging

from django.core.mail import send_mail
from django.urls import reverse

log = logging.getLogger(__name__)


def _get_from_email() -> str:
    """Devuelve el remitente configurado o uno por defecto."""
    try:
        from core.runtime_config import get_email_config
        cfg = get_email_config()
        return cfg.get("from_email") or "Comfutech Monitor <noreply@comfutech.local>"
    except Exception:
        return "Comfutech Monitor <noreply@comfutech.local>"


def send_verification_email(request, user, token):
    """
    Envía el email con el enlace de verificación.

    Args:
        request: HttpRequest para construir URL absoluta.
        user: instancia de User.
        token: UUID del token de verificación.

    Returns:
        tuple: (ok: bool, error: str | None)
    """
    try:
        verify_path = reverse("core:verify_email", kwargs={"token": str(token)})
        verify_url = request.build_absolute_uri(verify_path)

        name = user.get_full_name() or user.username
        from_email = _get_from_email()

        subject = "[Comfutech Monitor] Verifica tu correo electrónico"

        message = (
            f"Hola {name},\n\n"
            f"Para verificar tu correo electrónico en Comfutech Monitor, "
            f"haz clic en el siguiente enlace:\n\n"
            f"{verify_url}\n\n"
            f"Este enlace es válido por 48 horas.\n\n"
            f"— Comfutech Monitor"
        )

        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px;
                    margin: 0 auto; padding: 20px;">
            <h2 style="color: #0d6efd;">Verificación de correo</h2>
            <p>Hola <strong>{name}</strong>,</p>
            <p>Verifica tu correo en <strong>Comfutech Monitor</strong>:</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{verify_url}"
                   style="background-color: #0d6efd; color: white;
                          padding: 12px 30px; text-decoration: none;
                          border-radius: 6px; font-weight: bold;">
                    Verificar mi correo
                </a>
            </p>
            <p style="color: #dc3545; font-size: 0.85rem;">
                <strong>Válido por 48 horas.</strong>
            </p>
        </div>
        """

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True, None

    except Exception as e:
        log.exception("Error enviando email de verificación a %s", user.email)
        return False, str(e)


def send_password_reset_email(request, user, code):
    """
    Envía el código de recuperación de contraseña.

    Args:
        request: HttpRequest.
        user: instancia de User.
        code: código de 8 dígitos.

    Returns:
        tuple: (ok: bool, error: str | None)
    """
    try:
        name = user.get_full_name() or user.username
        from_email = _get_from_email()

        subject = "[Comfutech Monitor] Código de recuperación de contraseña"

        message = (
            f"Hola {name},\n\n"
            f"Tu código de recuperación es:\n\n    {code}\n\n"
            f"Válido durante los próximos 5 minutos.\n\n"
            f"— Comfutech Monitor"
        )

        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px;
                    margin: 0 auto; padding: 20px;">
            <h2 style="color: #0d6efd;">Recuperación de contraseña</h2>
            <p>Tu código es:</p>
            <div style="background: #f5f7fa; padding: 20px;
                        text-align: center; border-radius: 8px;">
                <span style="font-size: 2rem; letter-spacing: 8px;
                             font-weight: bold; color: #0d6efd;
                             font-family: monospace;">{code}</span>
            </div>
            <p style="color: #dc3545;"><strong>Válido por 5 minutos.</strong></p>
        </div>
        """

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True, None
    except Exception as e:
        log.exception("Error enviando código de reset a %s", user.email)
        return False, str(e)