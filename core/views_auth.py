# core/views_auth.py
"""
Vistas de autenticación personalizadas.

Incluye:
  - CustomLoginView: redirige a setup inicial si no hay superusuario.
  - superadmin_setup: crea el primer superadministrador del sistema.
"""
import logging

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.shortcuts import redirect, render

log = logging.getLogger(__name__)


def superuser_exists() -> bool:
    """¿Existe al menos un superusuario activo?"""
    return User.objects.filter(is_superuser=True, is_active=True).exists()


class CustomLoginView(LoginView):
    """
    Login que redirige al setup inicial si no existe ningún superusuario.
    """
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        """Antes de procesar, verifica si existe un superusuario."""
        if not superuser_exists():
            return redirect("core:superadmin_setup")
        return super().dispatch(request, *args, **kwargs)


def _validate_setup_data(request):
    """
    Valida los datos del formulario de setup inicial.

    Returns:
        tuple: (data: dict, errors: list)
    """
    username = (request.POST.get("username") or "").strip()
    email = (request.POST.get("email") or "").strip().lower()
    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    p1 = request.POST.get("password1") or ""
    p2 = request.POST.get("password2") or ""

    errors = []

    if not username:
        errors.append("El nombre de usuario es obligatorio.")
    elif len(username) < 3:
        errors.append("El usuario debe tener al menos 3 caracteres.")
    elif " " in username:
        errors.append("El nombre de usuario no puede contener espacios.")
    elif User.objects.filter(username__iexact=username).exists():
        errors.append("Ese nombre de usuario ya está en uso.")

    if not email:
        errors.append("El email es obligatorio.")
    elif "@" not in email or "." not in email.split("@")[-1]:
        errors.append("El email no tiene un formato válido.")
    elif User.objects.filter(email__iexact=email).exists():
        errors.append("Ese correo ya está registrado.")

    if len(p1) < 8:
        errors.append("La contraseña debe tener al menos 8 caracteres.")
    elif len(p1) > 16:
        errors.append("La contraseña no puede superar los 16 caracteres.")
    if p1 != p2:
        errors.append("Las contraseñas no coinciden.")

    if not errors and p1:
        try:
            validate_password(p1)
        except ValidationError as e:
            errors.extend(e.messages)

    return {
        "username": username,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "password1": p1,
    }, errors


def superadmin_setup(request):
    """
    Crea el primer superadministrador del sistema.

    Solo es accesible si NO existe ningún superusuario activo.
    Al crear el superadmin, se marca su email como verificado.
    """
    if superuser_exists():
        return redirect("login")

    if request.method == "POST":
        data, errors = _validate_setup_data(request)

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            try:
                user = User.objects.create_superuser(
                    username=data["username"],
                    email=data["email"],
                    password=data["password1"],
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                )

                try:
                    from core.roles import set_user_role, ROLE_SUPERADMIN
                    set_user_role(user, ROLE_SUPERADMIN)
                except Exception as e:
                    log.warning("No se pudo asignar rol superadmin: %s", e)

                # Marcar email como verificado automáticamente
                try:
                    from core.models import EmailVerification
                    verification = EmailVerification.get_or_create_for(user)
                    if user.email:
                        verification.mark_verified(user.email)
                except Exception as e:
                    log.warning("No se pudo verificar email: %s", e)

                messages.success(
                    request,
                    f"✅ Superadministrador '{user.username}' creado. "
                    "Ya puedes iniciar sesión."
                )
                return redirect("login")

            except Exception as e:
                log.exception("Error creando el superadmin")
                messages.error(request, f"Error inesperado: {e}")

    return render(request, "core/superadmin_setup.html")