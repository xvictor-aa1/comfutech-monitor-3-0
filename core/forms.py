# core/forms.py
"""
Formularios de la app `core'.

Incluye:
  - UserCreateForm: crear usuarios con auto-envío de verificación.
  - UserEditForm: editar usuarios (solo superadmin puede cambiar email).
  - UserPasswordForm: cambiar contraseñas.

Validaciones aplicadas:
  - Email obligatorio y único en el sistema.
  - Nombre y apellido: solo letras (con acentos), espacios, guiones y apóstrofes.
  - Nombre de usuario: sin espacios, solo alfanuméricos + . _ -
  - Contraseñas: mínimo 8, máximo 16 caracteres.
  - Solo superadmins pueden modificar el correo de otros usuarios.
"""
import logging
import re

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import EmailVerification
from .roles import (
    get_user_role, assignable_roles, get_role_display,
    ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_USER,
)

log = logging.getLogger(__name__)


# ============================================================
# PATRONES DE VALIDACIÓN
# ============================================================
# Longitud: 1-20
# Solo letras (incluye acentos, ñ, ü), espacios, apóstrofes y guiones.
NAME_PATTERN = re.compile(r"^[A-Za-zÁÉÍÓÚáéíóúÑñÜü\s'\-]{1,20}$")

# Username: solo alfanuméricos, punto, guion bajo, guion medio.
# NO permite espacios. Longitud: 3-10.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{3,10}$")

# Contraseña: longitud mínima y máxima.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 16


# ============================================================
# HELPERS DE VALIDACIÓN
# ============================================================
def _validate_email_unique(email: str, exclude_user_id: int = None):
    """
    Lanza ValidationError si el email ya existe en otro usuario.

    Args:
        email: correo a validar.
        exclude_user_id: ID de usuario a excluir (para edición).
    """
    if not email:
        return
    qs = User.objects.filter(email__iexact=email)
    if exclude_user_id:
        qs = qs.exclude(pk=exclude_user_id)
    if qs.exists():
        raise ValidationError(
            f"El correo '{email}' ya está registrado con otro usuario. "
            "Cada correo solo puede usarse en un usuario."
        )


def _validate_name(value: str, field_label: str = "Este campo"):
    """
    Valida que un nombre/apellido solo contenga letras válidas.

    Args:
        value: valor a validar.
        field_label: etiqueta del campo para el mensaje de error.

    Raises:
        ValidationError si contiene caracteres no permitidos.
    """
    if not value:
        return value
    value = value.strip()
    if not NAME_PATTERN.match(value):
        raise ValidationError(
            f"{field_label} solo puede contener letras, espacios, "
            "guiones y apóstrofes. No se permiten números ni símbolos."
        )
    return value


def _validate_password_strength(password: str, user=None):
    """
    Valida la longitud y fuerza de la contraseña.

    Args:
        password: contraseña a validar.
        user: usuario opcional para validaciones de Django.

    Raises:
        ValidationError si la contraseña no cumple los requisitos.
    """
    if not password:
        raise ValidationError("La contraseña es obligatoria.")

    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(
            f"La contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres."
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationError(
            f"La contraseña no puede superar los {PASSWORD_MAX_LENGTH} caracteres."
        )

    try:
        validate_password(password, user)
    except ValidationError as e:
        raise ValidationError(e.messages)


def _send_verification_email_for(user, request, reset_existing: bool = False):
    """
    Envía el email de verificación a un usuario.

    Args:
        user: instancia de User.
        request: HttpRequest para construir la URL absoluta.
        reset_existing: si True, invalida la verificación anterior y
                        genera un token nuevo. Si False, usa el existente.

    Returns:
        tuple: (ok: bool, error: str | None)
    """
    if not user.email:
        return False, "El usuario no tiene correo asignado."

    if request is None:
        return False, "No hay request para construir la URL."

    try:
        verification = EmailVerification.get_or_create_for(user)

        # Si ya está verificado y no se pidió reset, no reenviar
        if (not reset_existing
                and verification.verified
                and verification.verified_email
                and verification.verified_email.lower() == user.email.lower()):
            return True, None

        # Generar token nuevo
        token = verification.regenerate_token()

        # Enviar email
        from core.email_utils import send_verification_email
        return send_verification_email(request, user, token)

    except Exception as e:
        log.exception("Error enviando verificación a %s", user.email)
        return False, str(e)


# ============================================================
# CREAR USUARIO
# ============================================================
class UserCreateForm(forms.Form):
    """
    Formulario para crear un nuevo usuario.

    Auto-envía el correo de verificación tras crear el usuario.
    Requiere que el request se pase desde la vista.
    """

    username = forms.CharField(
        max_length=10, required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autofocus": True,
            "autocomplete": "off",
            "placeholder": "Ej: jperez",
        }),
        label="Nombre de usuario",
    )
    first_name = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ej: Juan",
            "autocomplete": "off",
        }),
        label="Nombre",
    )
    last_name = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ej: Pérez",
            "autocomplete": "off",
        }),
        label="Apellido",
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "id": "id_email",
            "autocomplete": "off",
            "placeholder": "usuario@dominio.com",
        }),
        label="Email",
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "id": "id_password1",
            "autocomplete": "new-password",
            "minlength": PASSWORD_MIN_LENGTH,
            "maxlength": PASSWORD_MAX_LENGTH,
        }),
        label="Contraseña",
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "id": "id_password2",
            "autocomplete": "new-password",
            "minlength": PASSWORD_MIN_LENGTH,
            "maxlength": PASSWORD_MAX_LENGTH,
        }),
        label="Repetir contraseña",
    )
    role = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Rol",
    )

    def __init__(self, *args, current_user=None, request=None, **kwargs):
        """
        Inicializa el formulario.

        Args:
            current_user: usuario que crea (para roles permitidos).
            request: HttpRequest (para enviar el email de verificación).
        """
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        self.request = request

        allowed = assignable_roles(current_user)
        allowed = [r for r in allowed if r != ROLE_SUPERADMIN]
        self.fields["role"].choices = [
            (r, get_role_display(r)) for r in allowed
        ]

    def clean_username(self):
        """Valida que el username sea único, sin espacios y con formato correcto."""
        username = (self.cleaned_data.get("username") or "").strip()

        if " " in username:
            raise ValidationError("El nombre de usuario no puede contener espacios.")

        if not USERNAME_PATTERN.match(username):
            raise ValidationError(
                "El nombre de usuario solo puede contener letras, números, "
                "puntos, guiones y guiones bajos (sin espacios)."
            )

        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Ese nombre de usuario ya está en uso.")

        return username

    def clean_first_name(self):
        """Valida que el nombre solo contenga caracteres permitidos."""
        return _validate_name(self.cleaned_data.get("first_name", ""), "El nombre")

    def clean_last_name(self):
        """Valida que el apellido solo contenga caracteres permitidos."""
        return _validate_name(self.cleaned_data.get("last_name", ""), "El apellido")

    def clean_email(self):
        """Valida que el email sea único en el sistema."""
        email = (self.cleaned_data.get("email") or "").strip().lower()
        _validate_email_unique(email)
        return email

    def clean_password1(self):
        """Valida la longitud y fuerza de la contraseña."""
        p1 = self.cleaned_data.get("password1") or ""
        _validate_password_strength(p1)
        return p1

    def clean(self):
        """Valida que las contraseñas coincidan."""
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")

        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contraseñas no coinciden.")

        return cleaned

    def save(self):
        """
        Crea el usuario, asigna el rol, crea el registro de verificación
        y envía automáticamente el correo de verificación.

        Returns:
            tuple: (user: User, email_ok: bool, email_error: str | None)
        """
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data["username"],
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            email=data.get("email", ""),
            password=data["password1"],
        )

        from .roles import set_user_role
        set_user_role(user, data["role"])

        # Crear registro de verificación
        EmailVerification.get_or_create_for(user)

        # Enviar correo de verificación automáticamente
        email_ok, email_error = _send_verification_email_for(
            user, self.request, reset_existing=True
        )

        return user, email_ok, email_error


# ============================================================
# EDITAR USUARIO
# ============================================================
class UserEditForm(forms.Form):
    """
    Formulario para editar un usuario existente.

    Reglas:
      - Solo el Superadministrador puede cambiar el correo.
      - Al cambiar el correo, se invalida el anterior y se envía
        automáticamente un enlace de verificación al nuevo.
    """

    first_name = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ej: Juan",
        }),
        label="Nombre",
    )
    last_name = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ej: Pérez",
        }),
        label="Apellido",
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "id": "id_email",
            "autocomplete": "off",
        }),
        label="Email",
    )
    role = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Rol",
    )

    def __init__(self, *args, current_user=None, target_user=None,
                 request=None, **kwargs):
        """
        Inicializa el formulario.

        Args:
            current_user: usuario que edita.
            target_user: usuario a editar.
            request: HttpRequest (para enviar emails).
        """
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        self.target_user = target_user
        self.request = request

        if target_user:
            self.fields["first_name"].initial = target_user.first_name
            self.fields["last_name"].initial = target_user.last_name
            self.fields["email"].initial = target_user.email
            self.fields["role"].initial = get_user_role(target_user)

        allowed = assignable_roles(current_user)
        allowed = [r for r in allowed if r != ROLE_SUPERADMIN]
        self.fields["role"].choices = [
            (r, get_role_display(r)) for r in allowed
        ]

    def _can_change_email(self) -> bool:
        """True si el usuario actual puede cambiar el email del target."""
        if not self.current_user or not self.current_user.is_authenticated:
            return False
        return self.current_user.is_superuser

    def clean_first_name(self):
        """Valida que el nombre solo contenga caracteres permitidos."""
        return _validate_name(self.cleaned_data.get("first_name", ""), "El nombre")

    def clean_last_name(self):
        """Valida que el apellido solo contenga caracteres permitidos."""
        return _validate_name(self.cleaned_data.get("last_name", ""), "El apellido")

    def clean_email(self):
        """
        Valida el email:
          - Si cambió y el actor NO es superadmin → error.
          - Si el nuevo email ya está en uso → error.
        """
        email = (self.cleaned_data.get("email") or "").strip().lower()

        if not self.target_user:
            return email

        old_email = (self.target_user.email or "").strip().lower()
        email_changed = old_email != email

        if email_changed and not self._can_change_email():
            raise ValidationError(
                "Solo el Superadministrador puede cambiar el correo "
                "electrónico de los usuarios."
            )

        exclude_id = self.target_user.pk if self.target_user else None
        _validate_email_unique(email, exclude_user_id=exclude_id)
        return email

    def save(self):
        """
        Guarda los cambios. Si el email cambió:
          - Invalida la verificación anterior.
          - Envía un nuevo enlace al correo nuevo.

        Returns:
            tuple: (user: User, email_changed: bool,
                    email_ok: bool, email_error: str | None)
        """
        data = self.cleaned_data
        u = self.target_user

        old_email = (u.email or "").strip().lower()
        new_email = (data.get("email") or "").strip().lower()
        email_changed = old_email != new_email

        u.first_name = data.get("first_name", "")
        u.last_name = data.get("last_name", "")
        u.email = data.get("email", "")
        u.save()

        email_ok = True
        email_error = None

        # Si el email cambió, resetear verificación y enviar nuevo enlace
        if email_changed:
            try:
                verification = EmailVerification.get_or_create_for(u)
                verification.reset_verification()
            except Exception:
                pass

            email_ok, email_error = _send_verification_email_for(
                u, self.request, reset_existing=True
            )

        # Nunca cambiar el propio rol
        if self.current_user and u.pk == self.current_user.pk:
            return u, email_changed, email_ok, email_error

        from .roles import set_user_role
        new_role = data["role"]
        if new_role != get_user_role(u):
            set_user_role(u, new_role)

        return u, email_changed, email_ok, email_error


# ============================================================
# CAMBIAR CONTRASEÑA
# ============================================================
class UserPasswordForm(forms.Form):
    """
    Formulario para cambiar la contraseña de un usuario.
    """

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "id": "id_password1",
            "autocomplete": "new-password",
            "minlength": PASSWORD_MIN_LENGTH,
            "maxlength": PASSWORD_MAX_LENGTH,
        }),
        label="Nueva contraseña",
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "id": "id_password2",
            "autocomplete": "new-password",
            "minlength": PASSWORD_MIN_LENGTH,
            "maxlength": PASSWORD_MAX_LENGTH,
        }),
        label="Repetir contraseña",
    )

    def __init__(self, *args, target_user=None, **kwargs):
        """
        Inicializa el formulario.

        Args:
            target_user: usuario cuya contraseña se cambia.
        """
        super().__init__(*args, **kwargs)
        self.target_user = target_user

    def clean_password1(self):
        """Valida la longitud y fuerza de la contraseña."""
        p1 = self.cleaned_data.get("password1") or ""
        _validate_password_strength(p1, self.target_user)
        return p1

    def clean(self):
        """Valida que las contraseñas coincidan."""
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")

        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contraseñas no coinciden.")

        return cleaned

    def save(self):
        """
        Aplica la nueva contraseña.

        Returns:
            User: el usuario actualizado.
        """
        pwd = self.cleaned_data["password1"]
        u = self.target_user
        u.set_password(pwd)
        u.save()
        return u