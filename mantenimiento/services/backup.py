# mantenimiento/services/backup.py
"""
Servicio de respaldos (backups) del sistema.

Responsabilidades:
  - Crear backups de la BD (MySQL: mysqldump, Postgres: pg_dump,
    SQLite: sqlite3.backup) con gzip.
  - Crear backups de los archivos .toml (config.toml + system.toml).
  - Crear backups completos (BD + .toml en un .zip).
  - Listar backups existentes.
  - Aplicar retención (eliminar backups > N días).
  - Descargar y eliminar backups.

Estructura del directorio `backup/`:
    backup/
    ├── db_2026-10-26_03-00-00.sql.gz
    ├── config_2026-10-26_03-00-00.zip
    └── full_2026-10-26_03-00-00.zip

Formato de nombre:
    <type>_<YYYY-MM-DD>_<HH-MM-SS>.<ext>

Seguridad:
  - Archivos con permisos 0600, directorio con 0700 (Unix).
  - Credenciales MySQL vía `--defaults-extra-file` (no visibles en `ps`).
  - Credenciales Postgres vía `PGPASSWORD` env var.
  - Nombres validados contra regex estricta (no path traversal).
  - Lock para evitar backups concurrentes.

Robustez v4:
  - Si mysqldump/pg_dump excede MYSQLDUMP_TIMEOUT, el subprocess se
    MATA (`proc.kill()`) antes de propagar la excepción. Antes quedaba
    huérfano consumiendo CPU y disco.
"""
import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from django.conf import settings

from core import config_ini

log = logging.getLogger(__name__)

# ============================================================
# CONFIGURACIÓN
# ============================================================
BACKUP_DIR: Path = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backup"))

_VALID_NAME_RE = re.compile(
    r"^(db|config|full)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.(sql\.gz|zip)$"
)

_backup_lock = threading.Lock()

MYSQLDUMP_TIMEOUT = 600           # 10 minutos
MIN_FREE_SPACE = 100 * 1024 * 1024  # 100 MB


# ============================================================
# HELPERS
# ============================================================
def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_backup_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "posix":
            os.chmod(BACKUP_DIR, 0o700)
    except Exception as e:
        log.warning("No se pudo ajustar permisos de %s: %s", BACKUP_DIR, e)


def _check_disk_space() -> None:
    _ensure_backup_dir()
    try:
        usage = shutil.disk_usage(BACKUP_DIR)
        if usage.free < MIN_FREE_SPACE:
            free_mb = usage.free // (1024 * 1024)
            raise Exception(
                f"Poco espacio en disco: {free_mb} MB libres. "
                f"Mínimo requerido: {MIN_FREE_SPACE // (1024*1024)} MB."
            )
    except OSError as e:
        log.warning("No se pudo verificar espacio en disco: %s", e)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _apply_file_permissions(path: Path) -> None:
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
    except Exception as e:
        log.warning("No se pudo ajustar permisos de %s: %s", path, e)


def _validate_filename(filename: str) -> bool:
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return False
    return bool(_VALID_NAME_RE.match(filename))


def _type_from_filename(filename: str) -> str:
    if filename.startswith("db_"):
        return "db"
    if filename.startswith("config_"):
        return "config"
    if filename.startswith("full_"):
        return "full"
    return "unknown"


# ============================================================
# DETECCIÓN DE MOTOR DE BD
# ============================================================
def _get_db_engine() -> str:
    """Devuelve 'mysql' | 'postgres' | 'sqlite' según settings."""
    from django.conf import settings as dj
    engine = dj.DATABASES["default"]["ENGINE"].lower()
    if "postgres" in engine:
        return "postgres"
    if "sqlite" in engine:
        return "sqlite"
    return "mysql"


# ============================================================
# HELPERS DE HERRAMIENTA DE DUMP (mysql/postgres)
# ============================================================
def _find_dump_tool(engine: str) -> Optional[str]:
    """
    Localiza el binario de dump para el engine indicado.

    Prioridad:
      1. `dump_tool_path` (o `mysql_dump_path` legacy) en [maintenance]
      2. PATH del sistema
      3. Rutas comunes por SO
    """
    cfg = config_ini.get_section("maintenance")
    custom = (
        (cfg.get("dump_tool_path") or "").strip()
        or (cfg.get("mysql_dump_path") or "").strip()  # legacy
    )
    if custom and Path(custom).is_file():
        return custom

    exe_name = "mysqldump" if engine == "mysql" else "pg_dump"
    if os.name == "nt":
        exe_name += ".exe"

    found = shutil.which(exe_name)
    if found:
        return found

    if engine == "mysql":
        candidates = [
            r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe",
            r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
            r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe",
            r"C:\Program Files\MariaDB 11.4\bin\mysqldump.exe",
            r"C:\Program Files\MariaDB 10.11\bin\mysqldump.exe",
            r"C:\xampp\mysql\bin\mysqldump.exe",
            r"C:\wamp64\bin\mysql\mysql8.0.31\bin\mysqldump.exe",
            r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqldump.exe",
            "/usr/bin/mysqldump",
            "/usr/local/bin/mysqldump",
            "/opt/homebrew/bin/mysqldump",
        ]
    else:  # postgres
        candidates = [
            r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
            r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
            r"C:\Program Files\PostgreSQL\14\bin\pg_dump.exe",
            "/usr/bin/pg_dump",
            "/usr/local/bin/pg_dump",
            "/opt/homebrew/bin/pg_dump",
            "/Library/PostgreSQL/16/bin/pg_dump",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def _mysqldump_needs_column_statistics(path: str) -> bool:
    """True si es MySQL 8.0+ (necesita --column-statistics=0)."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        v = (result.stdout or "") + (result.stderr or "")
        m = re.search(r"Ver\s+(\d+)\.", v, re.IGNORECASE)
        if m:
            return int(m.group(1)) >= 8
    except Exception:
        pass
    return False


def _create_mysql_defaults_file(user: str, password: str, host: str, port: str) -> str:
    """Archivo temporal con credenciales MySQL (no visible en `ps`)."""
    fd, path = tempfile.mkstemp(prefix=".mysql_", suffix=".cnf")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[client]\n")
        f.write(f"user={user}\n")
        if password:
            f.write(f"password={password}\n")
        f.write(f"host={host}\n")
        f.write(f"port={port}\n")
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
    except Exception:
        pass
    return path


# ============================================================
# DUMP DE LA BD — DESPACHADOR POR ENGINE
# ============================================================
def _dump_db_to_path(output_path: Path) -> None:
    """
    Ejecuta el dump de la BD al archivo indicado (comprimido en gzip).

    Despacha según el engine configurado:
      - MySQL: mysqldump → gzip
      - Postgres: pg_dump → gzip
      - SQLite: sqlite3.backup() → gzip

    Raises:
        Exception con mensaje claro si la herramienta no está disponible.
    """
    engine = _get_db_engine()
    db = settings.DATABASES["default"]

    if engine == "sqlite":
        _dump_sqlite_to_path(db["NAME"], output_path)
        return

    if engine == "mysql":
        _dump_mysql_to_path(db, output_path)
        return

    if engine == "postgres":
        _dump_postgres_to_path(db, output_path)
        return

    raise Exception(f"Engine '{engine}' no soportado para backup.")


def _dump_sqlite_to_path(db_path, output_path: Path) -> None:
    """Copia segura de una BD SQLite (via sqlite3.backup())."""
    import sqlite3

    db_path = Path(db_path)
    if not db_path.is_file():
        raise Exception(f"Archivo SQLite no encontrado: {db_path}")

    # Copia temporal descomprimida.
    fd, tmp_sqlite = tempfile.mkstemp(prefix=".sqlite_", suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(tmp_sqlite)
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()

        # Comprimir.
        with open(tmp_sqlite, "rb") as f_in:
            with gzip.open(output_path, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
    finally:
        if os.path.exists(tmp_sqlite):
            try:
                os.unlink(tmp_sqlite)
            except Exception:
                pass


def _dump_mysql_to_path(db: dict, output_path: Path) -> None:
    """Dump MySQL con mysqldump."""
    mysqldump = _find_dump_tool("mysql")
    if not mysqldump:
        raise Exception(
            "No se encontró 'mysqldump'. Instala MySQL/MariaDB o "
            "configura 'dump_tool_path' en el Panel de Mantenimiento."
        )

    db_name = db.get("NAME", "")
    user = db.get("USER", "")
    password = db.get("PASSWORD", "")
    host = db.get("HOST", "127.0.0.1") or "127.0.0.1"
    port = str(db.get("PORT", "3306") or "3306")

    if not db_name:
        raise Exception("Falta DB NAME en la configuración.")

    temp_defaults = _create_mysql_defaults_file(user, password, host, port)
    try:
        cmd = [
            mysqldump,
            f"--defaults-extra-file={temp_defaults}",
            "--single-transaction", "--quick",
            "--routines", "--events", "--triggers",
            "--hex-blob",
            "--default-character-set=utf8mb4",
            db_name,
        ]
        if _mysqldump_needs_column_statistics(mysqldump):
            cmd.insert(2, "--column-statistics=0")

        log.info("mysqldump → %s", output_path.name)
        with gzip.open(output_path, "wb", compresslevel=6) as gz:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                shutil.copyfileobj(proc.stdout, gz)
            finally:
                proc.stdout.close()
                stderr_bytes = proc.stderr.read()
                proc.stderr.close()
                # v4: matar el subprocess si excede el timeout.
                try:
                    proc.wait(timeout=MYSQLDUMP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()  # esperar a que muera realmente
                    try:
                        output_path.unlink()
                    except Exception:
                        pass
                    raise Exception(
                        f"mysqldump excedió el timeout de "
                        f"{MYSQLDUMP_TIMEOUT}s y fue abortado."
                    )

        if proc.returncode != 0:
            try:
                output_path.unlink()
            except Exception:
                pass
            raise Exception(
                f"mysqldump falló: {stderr_bytes.decode('utf-8', errors='replace')[:500]}"
            )
    finally:
        if os.path.exists(temp_defaults):
            try:
                os.unlink(temp_defaults)
            except Exception:
                pass


def _dump_postgres_to_path(db: dict, output_path: Path) -> None:
    """Dump PostgreSQL con pg_dump."""
    pg_dump = _find_dump_tool("postgres")
    if not pg_dump:
        raise Exception(
            "No se encontró 'pg_dump'. Instala PostgreSQL o "
            "configura 'dump_tool_path' en el Panel de Mantenimiento."
        )

    db_name = db.get("NAME", "")
    user = db.get("USER", "")
    password = db.get("PASSWORD", "")
    host = db.get("HOST", "127.0.0.1") or "127.0.0.1"
    port = str(db.get("PORT", "5432") or "5432")

    if not db_name:
        raise Exception("Falta DB NAME en la configuración.")

    cmd = [
        pg_dump,
        "-h", host, "-p", port, "-U", user, "-d", db_name,
        "--no-owner",
        "--no-acl",
        "--schema=public",
        "--format=plain",
    ]

    # Credenciales vía env (no aparecen en `ps`).
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    log.info("pg_dump → %s", output_path.name)
    with gzip.open(output_path, "wb", compresslevel=6) as gz:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        try:
            shutil.copyfileobj(proc.stdout, gz)
        finally:
            proc.stdout.close()
            stderr_bytes = proc.stderr.read()
            proc.stderr.close()
            # v4: matar el subprocess si excede el timeout.
            try:
                proc.wait(timeout=MYSQLDUMP_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()  # esperar a que muera realmente
                try:
                    output_path.unlink()
                except Exception:
                    pass
                raise Exception(
                    f"pg_dump excedió el timeout de "
                    f"{MYSQLDUMP_TIMEOUT}s y fue abortado."
                )

    if proc.returncode != 0:
        try:
            output_path.unlink()
        except Exception:
            pass
        raise Exception(
            f"pg_dump falló: {stderr_bytes.decode('utf-8', errors='replace')[:500]}"
        )


# ============================================================
# BACKUP DE LA BD
# ============================================================
def backup_database() -> Dict:
    """
    Crea un backup completo de la BD en formato `.sql.gz`.

    Returns:
        dict: {filename, path, size, timestamp, type}
    """
    if not _backup_lock.acquire(blocking=False):
        raise Exception("Ya hay un backup en curso. Intenta en unos segundos.")
    try:
        _check_disk_space()
        _ensure_backup_dir()

        timestamp = _timestamp()
        filename = f"db_{timestamp}.sql.gz"
        filepath = BACKUP_DIR / filename

        _dump_db_to_path(filepath)
        _apply_file_permissions(filepath)
        size = filepath.stat().st_size

        log.info("Backup BD completado: %s (%d bytes)", filename, size)
        return {
            "filename": filename,
            "path": str(filepath),
            "size": size,
            "timestamp": timestamp,
            "type": "db",
        }
    finally:
        _backup_lock.release()


# ============================================================
# BACKUP DE LOS .TOML
# ============================================================
def backup_configs() -> Dict:
    """Crea un backup de `config.toml` y `system.toml` en formato `.zip`."""
    if not _backup_lock.acquire(blocking=False):
        raise Exception("Ya hay un backup en curso. Intenta en unos segundos.")
    try:
        _check_disk_space()
        _ensure_backup_dir()

        base_dir = Path(settings.BASE_DIR)
        files_to_backup = []
        for name in ("config.toml", "system.toml"):
            p = base_dir / name
            if p.is_file():
                files_to_backup.append(p)

        if not files_to_backup:
            raise Exception(
                "No se encontraron archivos .toml para respaldar "
                "(config.toml, system.toml)."
            )

        timestamp = _timestamp()
        filename = f"config_{timestamp}.zip"
        filepath = BACKUP_DIR / filename

        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in files_to_backup:
                zf.write(p, arcname=p.name)

        _apply_file_permissions(filepath)
        size = filepath.stat().st_size

        log.info("Backup config completado: %s (%d bytes)", filename, size)
        return {
            "filename": filename,
            "path": str(filepath),
            "size": size,
            "timestamp": timestamp,
            "type": "config",
            "files": [p.name for p in files_to_backup],
        }
    finally:
        _backup_lock.release()


# ============================================================
# BACKUP COMPLETO (DB + CONFIGS en ZIP)
# ============================================================
def backup_full() -> Dict:
    """Crea un backup completo: BD + .toml en un único .zip."""
    if not _backup_lock.acquire(blocking=False):
        raise Exception("Ya hay un backup en curso. Intenta en unos segundos.")
    try:
        _check_disk_space()
        _ensure_backup_dir()

        # 1. Dump de la BD a un archivo temporal.
        fd, db_temp = tempfile.mkstemp(prefix=".db_", suffix=".sql.gz")
        os.close(fd)
        try:
            _dump_db_to_path(Path(db_temp))

            # 2. Crear el ZIP con dump + .toml + manifest.
            timestamp = _timestamp()
            filename = f"full_{timestamp}.zip"
            filepath = BACKUP_DIR / filename

            base_dir = Path(settings.BASE_DIR)
            toml_files = [
                p for p in (base_dir / "config.toml", base_dir / "system.toml")
                if p.is_file()
            ]

            db_name = settings.DATABASES["default"].get("NAME", "")

            with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.write(db_temp, arcname="db.sql.gz")
                for p in toml_files:
                    zf.write(p, arcname=p.name)
                zf.writestr(
                    "manifest.json",
                    json.dumps({
                        "created_at": _utcnow_iso(),
                        "db_name": db_name,
                        "toml_files": [p.name for p in toml_files],
                    }, indent=2),
                )

            _apply_file_permissions(filepath)
            size = filepath.stat().st_size

            log.info("Backup full completado: %s (%d bytes)", filename, size)
            return {
                "filename": filename,
                "path": str(filepath),
                "size": size,
                "timestamp": timestamp,
                "type": "full",
                "components": ["db.sql.gz"] + [p.name for p in toml_files],
            }
        finally:
            if os.path.exists(db_temp):
                try:
                    os.unlink(db_temp)
                except Exception:
                    pass
    finally:
        _backup_lock.release()


# ============================================================
# BACKUP AUTOMÁTICO (según config)
# ============================================================
def backup_full_auto() -> Dict:
    """
    Ejecuta un backup automático según `backup_db` y `backup_config`.

    Actualiza `[_meta].last_backup_*` y aplica retención.
    """
    from core.runtime_config import get_maintenance_config
    cfg = get_maintenance_config()

    do_db = cfg.get("backup_db", True)
    do_cfg = cfg.get("backup_config", True)

    if not do_db and not do_cfg:
        raise Exception(
            "Nada que respaldar: activa 'backup_db' o 'backup_config'."
        )

    if do_db and do_cfg:
        result = backup_full()
    elif do_db:
        result = backup_database()
    else:
        result = backup_configs()

    try:
        config_ini.set_meta_value("last_backup_run", _utcnow_iso())
        config_ini.set_meta_value("last_backup_type", result["type"])
        config_ini.set_meta_value("last_backup_filename", result["filename"])
    except Exception as e:
        log.warning("No se pudo actualizar [_meta] del backup: %s", e)

    try:
        apply_retention()
    except Exception as e:
        log.warning("Error aplicando retención: %s", e)

    return result


# ============================================================
# LISTADO / DESCARGA / ELIMINACIÓN
# ============================================================
def list_backups() -> List[Dict]:
    """Lista los backups existentes (orden descendente por fecha)."""
    _ensure_backup_dir()
    result = []
    for f in BACKUP_DIR.iterdir():
        if not f.is_file() or not _validate_filename(f.name):
            continue
        try:
            stat = f.stat()
            result.append({
                "filename": f.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mtime_dt": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "type": _type_from_filename(f.name),
            })
        except Exception:
            continue
    result.sort(key=lambda x: x["mtime"], reverse=True)
    return result


def get_backup_path(filename: str) -> Optional[Path]:
    """Devuelve la ruta de un backup válido, o None."""
    if not _validate_filename(filename):
        return None
    path = BACKUP_DIR / filename
    if not path.is_file():
        return None
    return path


def delete_backup(filename: str) -> bool:
    """Elimina un backup. Retorna True si se eliminó."""
    path = get_backup_path(filename)
    if not path:
        return False
    try:
        path.unlink()
        log.info("Backup eliminado: %s", filename)
        return True
    except Exception as e:
        log.error("Error eliminando backup %s: %s", filename, e)
        return False


# ============================================================
# RETENCIÓN
# ============================================================
def apply_retention(days: Optional[int] = None) -> int:
    """Elimina backups con más de `days` días de antigüedad."""
    if days is None:
        from core.runtime_config import get_maintenance_config
        days = get_maintenance_config().get("retention_days", 30)

    if days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    for f in BACKUP_DIR.iterdir():
        if not f.is_file() or not _validate_filename(f.name):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
                log.info("Backup antiguo eliminado: %s", f.name)
        except Exception as e:
            log.warning("Error eliminando %s: %s", f.name, e)
    return deleted


# ============================================================
# ESTADÍSTICAS
# ============================================================
def get_stats() -> Dict:
    """
    Estadísticas globales del servicio de backups.

    Detecta el motor de BD y la herramienta de dump correspondiente
    (mysqldump / pg_dump / sqlite3 built-in).
    """
    _ensure_backup_dir()
    backups = list_backups()
    total_size = sum(b["size"] for b in backups)
    meta = config_ini.get_meta()
    engine = _get_db_engine()

    # Detectar la herramienta de dump según el motor.
    if engine == "sqlite":
        dump_tool = "sqlite3 (built-in)"
    else:
        dump_tool = _find_dump_tool(engine) or ""

    return {
        "count": len(backups),
        "total_size": total_size,
        "last_backup_run": meta.get("last_backup_run", ""),
        "last_backup_type": meta.get("last_backup_type", ""),
        "last_backup_filename": meta.get("last_backup_filename", ""),
        "backup_dir": str(BACKUP_DIR),
        "dump_tool_path": dump_tool,
        "db_engine": engine,
    }