# core/views_users.py
"""
Vistas de gestión de usuarios.

Incluye:
  - user_list: listado con filtros, ordenamiento y paginación.
  - user_create: crear usuario con auto-envío de verificación.
  - user_edit: editar usuario (email solo superadmin).
  - user_change_password: cambiar contraseña.
  - user_delete: eliminar usuario.
  - profile: editar el propio perfil.
"""
import logging

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import require_admin_or_super
from core.forms import UserCreateForm, UserEditForm, UserPasswordForm
from core.models import EmailVerification
from core.roles import (
    get_user_role, get_role_display, can_manage_users,
    ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_USER,
    GROUP_ADMIN, GROUP_USER,
)
from core.sorting import apply_sort, has_active_filters

log = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================
def _build_verification_map(users) -> dict:
    """
    Devuelve un dict {user_id: email_verified_bool} para una lista de users.

    Se hace en una sola query para evitar el problema N+1 (una consulta
    por cada usuario).

    Args:
        users: lista de instancias de User.

    Returns:
        dict: {user_id: bool} donde bool es True si el email está
              verificado Y coincide con el email actual del User.
    """
    user_ids = [u.id for u in users]
    if not user_ids:
        return {}

    verifications = EmailVerification.objects.filter(user_id__in=user_ids)
    verification_map = {v.user_id: v for v in verifications}

    result = {}
    for u in users:
        v = verification_map.get(u.id)
        is_verified = bool(
            v
            and v.verified
            and v.verified_email
            and (u.email or "").lower() == v.verified_email.lower()
        )
        result[u.id] = is_verified
    return result


# ============================================================
# LISTADO DE USUARIOS
# ============================================================
@require_admin_or_super()
def user_list(request):
    """
    Lista los usuarios con filtros, ordenamiento y paginación (10/pág).

    Filtros aceptados vía GET:
      - q: búsqueda por username, nombre, apellido o email.
      - role: superadmin / administrador / usuario / sin_rol.
      - status: 1=activos, 0=inactivos.
      - verified: 1=verificados, 0=sin verificar.
    """
    query = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "")
    status_filter = request.GET.get("status", "")
    verified_filter = request.GET.get("verified", "")

    # Query base
    users = User.objects.all()

    # Búsqueda libre
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )

    # Anotar el nombre del grupo para ordenar/filtrar por rol
    users = users.annotate(group_name=Max("groups__name"))

    # ============================================================
    # FIX: filtro por rol con casos especiales
    # ============================================================
    # `group_name` es el nombre del grupo de Django (Administrador,
    # Usuario), pero el rol "superadmin" NO usa grupo (usa is_superuser).
    # Por eso hay que tratar cada caso explícitamente.
    if role_filter:
        if role_filter == ROLE_SUPERADMIN:
            users = users.filter(is_superuser=True)
        elif role_filter == ROLE_ADMIN:
            users = users.filter(group_name=GROUP_ADMIN)
        elif role_filter == ROLE_USER:
            users = users.filter(group_name=GROUP_USER)
        elif role_filter == "sin_rol":
            users = users.filter(group_name__isnull=True, is_superuser=False)
        else:
            users = users.none()

    # Filtros de estado
    if status_filter == "1":
        users = users.filter(is_active=True)
    elif status_filter == "0":
        users = users.filter(is_active=False)

    # Ordenamiento
    SORTABLE = {
        "usuario":      "username",
        "nombre":       "first_name",
        "email":        "email",
        "rol":          "group_name",
        "activo":       "is_active",
        "ultimo_login": "last_login",
    }
    users, sort_key, order = apply_sort(request, users, SORTABLE, "username")

    users_list = list(users)
    verification_map = _build_verification_map(users_list)

    # Filtro por verificación (post-query, usando el mapa)
    if verified_filter == "1":
        users_list = [u for u in users_list if verification_map.get(u.id)]
    elif verified_filter == "0":
        users_list = [u for u in users_list if not verification_map.get(u.id)]

    # Construir datos enriquecidos según el rol del actor
    actor_role = get_user_role(request.user)
    users_data = []
    for u in users_list:
        u_role = get_user_role(u)

        # Los administradores solo ven usuarios normales y a sí mismos
        if actor_role == ROLE_ADMIN and u_role != ROLE_USER:
            if u.pk != request.user.pk:
                continue

        users_data.append({
            "user": u,
            "role": u_role,
            "role_display": get_role_display(u_role),
            "email_verified": verification_map.get(u.id, False),
            "can_edit": can_manage_users(request.user, u) or u.pk == request.user.pk,
            "can_delete": can_manage_users(request.user, u) and u.pk != request.user.pk,
            "can_change_email": request.user.is_superuser,
        })

    # ============================================================
    # Paginación: 10 usuarios por página
    # ============================================================
    paginator = Paginator(users_data, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # ============================================================
    # Stats globales (basadas en TODOS los usuarios, no solo la página)
    # ============================================================
    all_users = User.objects.all()
    total_users = all_users.count()
    active_users = all_users.filter(is_active=True).count()

    verifs = {v.user_id: v for v in EmailVerification.objects.all()}
    verified_count = 0
    for u in all_users.only("id", "email"):
        v = verifs.get(u.id)
        if (v and v.verified and v.verified_email
                and (u.email or "").lower() == v.verified_email.lower()):
            verified_count += 1
    unverified_count = total_users - verified_count

    context = {
        "users_data": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "verified_filter": verified_filter,
        "sort_key": sort_key,
        "order": order,
        "is_superadmin": actor_role == ROLE_SUPERADMIN,
        "role_choices": [
            (ROLE_SUPERADMIN, "Superadministrador"),
            (ROLE_ADMIN, "Administrador"),
            (ROLE_USER, "Usuario"),
            ("sin_rol", "Sin rol"),
        ],
        # Stats
        "total_users": total_users,
        "active_users": active_users,
        "verified_count": verified_count,
        "unverified_count": unverified_count,
        # Filtros activos
        "has_filters": has_active_filters(
            request, ["q", "role", "status", "verified"]
        ),
    }
    return render(request, "core/user_list.html", context)


# ============================================================
# CREAR USUARIO
# ============================================================
@require_admin_or_super()
def user_create(request):
    """
    Crea un nuevo usuario y envía automáticamente el correo de verificación.

    El envío se hace dentro del propio `UserCreateForm.save()`, que recibe
    el `request` para construir la URL absoluta del enlace.
    """
    if request.method == "POST":
        form = UserCreateForm(
            request.POST,
            current_user=request.user,
            request=request,
        )
        if form.is_valid():
            user, email_ok, email_error = form.save()

            if email_ok:
                messages.success(
                    request,
                    f"Usuario '{user.username}' creado. "
                    f"Se envió el enlace de verificación a {user.email}."
                )
            else:
                messages.warning(
                    request,
                    f"Usuario '{user.username}' creado, pero no se pudo "
                    f"enviar el correo de verificación: {email_error}. "
                    "Puedes reenviarlo desde la lista de usuarios."
                )

            return redirect("core:user_list")
    else:
        form = UserCreateForm(
            current_user=request.user,
            request=request,
        )

    context = {
        "form": form,
        "title": "Nuevo usuario",
        "is_edit": False,
        "email_verified": False,
    }
    return render(request, "core/user_form.html", context)


# ============================================================
# EDITAR USUARIO
# ============================================================
@require_admin_or_super()
def user_edit(request, user_id):
    """
    Edita un usuario existente.

    Reglas:
      - Solo el Superadministrador puede cambiar el email.
      - Al cambiar el email, se invalida la verificación anterior y
        se envía automáticamente un nuevo enlace al correo nuevo.
    """
    target = get_object_or_404(User, pk=user_id)

    is_self = target.pk == request.user.pk
    if not is_self and not can_manage_users(request.user, target):
        raise PermissionDenied("No puedes editar a este usuario.")

    if request.method == "POST":
        form = UserEditForm(
            request.POST,
            current_user=request.user,
            target_user=target,
            request=request,
        )
        if form.is_valid():
            user, email_changed, email_ok, email_error = form.save()

            if email_changed:
                if email_ok:
                    messages.success(
                        request,
                        f"Usuario '{user.username}' actualizado. "
                        f"Se envió el nuevo enlace de verificación a {user.email}."
                    )
                else:
                    messages.warning(
                        request,
                        f"Usuario '{user.username}' actualizado, pero no se "
                        f"pudo enviar el correo: {email_error}."
                    )
            else:
                messages.success(request, f"Usuario '{user.username}' actualizado.")

            return redirect("core:user_list")
    else:
        form = UserEditForm(
            current_user=request.user,
            target_user=target,
            request=request,
        )

    email_verified = EmailVerification.is_email_verified(target)

    context = {
        "form": form,
        "title": f"Editar usuario: {target.username}",
        "target_user": target,
        "is_edit": True,
        "email_verified": email_verified,
        "can_change_email": request.user.is_superuser,
    }
    return render(request, "core/user_form.html", context)


# ============================================================
# CAMBIAR CONTRASEÑA
# ============================================================
@require_admin_or_super()
def user_change_password(request, user_id):
    """Cambia la contraseña de un usuario existente."""
    target = get_object_or_404(User, pk=user_id)

    is_self = target.pk == request.user.pk
    if not is_self and not can_manage_users(request.user, target):
        raise PermissionDenied("No puedes cambiar la contraseña de este usuario.")

    if request.method == "POST":
        form = UserPasswordForm(request.POST, target_user=target)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"Contraseña de '{target.username}' actualizada."
            )
            return redirect("core:user_list")
    else:
        form = UserPasswordForm(target_user=target)

    context = {
        "form": form,
        "title": f"Cambiar contraseña: {target.username}",
        "target_user": target,
    }
    return render(request, "core/user_password.html", context)


# ============================================================
# ELIMINAR USUARIO
# ============================================================
@require_admin_or_super()
def user_delete(request, user_id):
    """Elimina un usuario (con confirmación previa)."""
    target = get_object_or_404(User, pk=user_id)

    if target.pk == request.user.pk:
        raise PermissionDenied("No puedes eliminarte a ti mismo.")

    if not can_manage_users(request.user, target):
        raise PermissionDenied("No puedes eliminar a este usuario.")

    if request.method == "POST":
        username = target.username
        target.delete()
        messages.success(request, f"Usuario '{username}' eliminado.")
        return redirect("core:user_list")

    context = {"target_user": target}
    return render(request, "core/user_confirm_delete.html", context)


# ============================================================
# PERFIL PROPIO
# ============================================================
@login_required
def profile(request):
    """
    Edita el perfil del usuario logueado.

    Reglas:
      - El usuario NO puede cambiar su propio email.
      - El usuario NO puede cambiar su propio rol.
    """
    user = request.user

    if request.method == "POST":
        form = UserEditForm(
            request.POST,
            current_user=request.user,
            target_user=user,
            request=request,
        )
        if form.is_valid():
            form.cleaned_data["role"] = get_user_role(user)
            form.save()
            messages.success(request, "Perfil actualizado.")
            return redirect("core:profile")
    else:
        form = UserEditForm(
            current_user=request.user,
            target_user=user,
            request=request,
        )
        form.fields["role"].disabled = True
        form.fields["email"].disabled = True

    context = {
        "form": form,
        "user_obj": user,
        "email_verified": EmailVerification.is_email_verified(user),
    }
    return render(request, "core/profile.html", context)