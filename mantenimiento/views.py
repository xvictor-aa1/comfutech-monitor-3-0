# mantenimiento/views.py
"""
Vistas del Panel de Mantenimiento (solo superadmin).
"""
import logging
import re

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

from core import config_ini
from core.decorators import require_superadmin
from core.runtime_config import get_maintenance_config
from .services import backup as backup_service

log = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================
def _sanitize_time(s: str) -> str:
    """Valida HH:MM; retorna '03:00' si es inválido."""
    s = (s or "").strip()
    m = re.match(r"^(\d{2}):(\d{2})$", s)
    if not m:
        return "03:00"
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return "03:00"
    return f"{h:02d}:{mi:02d}"


def _clamp_int(v, min_v: int, max_v: int, default: int) -> int:
    try:
        n = int(v)
    except (ValueError, TypeError):
        return default
    return max(min_v, min(max_v, n))


def _register_backup_meta(result: dict) -> None:
    """Registra el backup en [_meta]."""
    try:
        config_ini.set_meta_value("last_backup_run", backup_service._utcnow_iso())
        config_ini.set_meta_value("last_backup_type", result.get("type", ""))
        config_ini.set_meta_value("last_backup_filename", result.get("filename", ""))
    except Exception as e:
        log.warning("No se pudo registrar en [_meta]: %s", e)


# ============================================================
# PANEL PRINCIPAL
# ============================================================
@require_superadmin()
def panel(request):
    """
    Panel principal de mantenimiento.

    GET:  muestra config + lista de backups.
    POST: guarda la configuración del backup automático.
    """
    if request.method == "POST":
        updates = {
            "auto_backup_enabled": "true" if request.POST.get("auto_backup_enabled") == "on" else "false",
            "backup_time": _sanitize_time(request.POST.get("backup_time", "03:00")),
            "backup_on_startup": "true" if request.POST.get("backup_on_startup") == "on" else "false",
            "backup_db": "true" if request.POST.get("backup_db") == "on" else "false",
            "backup_config": "true" if request.POST.get("backup_config") == "on" else "false",
            "retention_days": str(_clamp_int(request.POST.get("retention_days"), 0, 365, 30)),
            "mysql_dump_path": (request.POST.get("dump_tool_path") or "").strip(),
        }

        try:
            config_ini.write_sections(
                {"maintenance": updates},
                updated_by=request.user.username,
            )
            messages.success(
                request,
                "Configuración guardada. El monitor la aplicará en menos "
                "de 60 segundos.",
            )
        except Exception as e:
            log.exception("Error guardando config de mantenimiento")
            messages.error(request, f"No se pudo guardar la configuración: {e}")
        return redirect("mantenimiento:panel")

    cfg = get_maintenance_config()
    stats = backup_service.get_stats()
    backups = backup_service.list_backups()

    context = {
        "cfg": cfg,
        "stats": stats,
        "backups": backups,
    }
    return render(request, "mantenimiento/panel.html", context)


# ============================================================
# BACKUPS MANUALES
# ============================================================
@require_superadmin()
def backup_db(request):
    """Crea un backup de la BD ahora."""
    if request.method != "POST":
        return redirect("mantenimiento:panel")
    try:
        result = backup_service.backup_database()
        _register_backup_meta(result)
        messages.success(
            request,
            f"✓ Backup de BD creado: {result['filename']} "
            f"({result['size'] // 1024} KB)",
        )
    except Exception as e:
        log.exception("Error backup BD")
        messages.error(request, f"❌ Error: {e}")
    return redirect("mantenimiento:panel")


@require_superadmin()
def backup_configs(request):
    """Crea un backup de los .toml ahora."""
    if request.method != "POST":
        return redirect("mantenimiento:panel")
    try:
        result = backup_service.backup_configs()
        _register_backup_meta(result)
        messages.success(
            request,
            f"✓ Backup de configs creado: {result['filename']} "
            f"({result['size'] // 1024} KB)",
        )
    except Exception as e:
        log.exception("Error backup configs")
        messages.error(request, f"❌ Error: {e}")
    return redirect("mantenimiento:panel")


@require_superadmin()
def backup_full(request):
    """Crea un backup completo (BD + configs) ahora."""
    if request.method != "POST":
        return redirect("mantenimiento:panel")
    try:
        result = backup_service.backup_full()
        _register_backup_meta(result)
        messages.success(
            request,
            f"✓ Backup completo creado: {result['filename']} "
            f"({result['size'] // 1024} KB)",
        )
    except Exception as e:
        log.exception("Error backup full")
        messages.error(request, f"❌ Error: {e}")
    return redirect("mantenimiento:panel")


# ============================================================
# DESCARGA / ELIMINACIÓN
# ============================================================
@require_superadmin()
def download_backup(request, filename):
    """Descarga un backup (validación estricta de nombre)."""
    path = backup_service.get_backup_path(filename)
    if not path:
        raise Http404("Backup no encontrado o nombre inválido")
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=filename,
    )


@require_superadmin()
def delete_backup(request, filename):
    """Elimina un backup (requiere POST)."""
    if request.method != "POST":
        return redirect("mantenimiento:panel")
    if backup_service.delete_backup(filename):
        messages.success(request, f"✓ Backup eliminado: {filename}")
    else:
        messages.error(request, f"❌ No se pudo eliminar: {filename}")
    return redirect("mantenimiento:panel")


# ============================================================
# RETENCIÓN MANUAL
# ============================================================
@require_superadmin()
def apply_retention_now(request):
    """Aplica retención manualmente."""
    if request.method != "POST":
        return redirect("mantenimiento:panel")
    try:
        deleted = backup_service.apply_retention()
        if deleted:
            messages.success(request, f"✓ Se eliminaron {deleted} backup(s) antiguos.")
        else:
            messages.info(request, "No hay backups antiguos para eliminar.")
    except Exception as e:
        messages.error(request, f"❌ Error: {e}")
    return redirect("mantenimiento:panel")