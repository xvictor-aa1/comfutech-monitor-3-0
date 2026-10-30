# 🖥️ Comfutech Monitor

Sistema de monitoreo de red para **Comfutech** en Güigüe, Estado Carabobo, Venezuela.

Permite supervisar en tiempo real el estado de equipos de red (MikroTik, Cisco, Huawei, Ubiquiti, Cambium y genéricos) vía **SNMP**, **ICMP** y **TCP**, con visualización en **Grafana**, notificaciones por **Telegram**, recuperación de contraseña por email y gestión completa desde una interfaz web **Django**.

**Versión actual:** 3.0 (TOML + mantenimiento + alertas v2 con grupos)  
**Estado:** Producción  
**Última actualización:** Octubre 2026

---

# 📑 Tabla de contenido

1. [Descripción general](#-descripción-general)
2. [Historia del proyecto](#-historia-del-proyecto)
3. [Arquitectura del sistema](#️-arquitectura-del-sistema)
4. [Stack tecnológico](#️-stack-tecnológico)
5. [Características principales](#-características-principales)
6. [Diagramas de flujo por apartado](#️-diagramas-de-flujo-por-apartado)
7. [Estructura del proyecto](#-estructura-del-proyecto)
8. [Requisitos previos](#-requisitos-previos)
9. [Instalación paso a paso](#-instalación-paso-a-paso)
10. [Configuración (TOML)](#️-configuración-toml)
11. [Base de datos](#-base-de-datos)
12. [Motor de monitoreo](#-motor-de-monitoreo)
13. [Sistema de alertas v2](#-sistema-de-alertas-v2-grupos--operadores)
14. [Sistema de usuarios](#-sistema-de-usuarios)
15. [Panel de Mantenimiento](#-panel-de-mantenimiento-backups)
16. [Django Admin](#️-django-admin)
17. [Interfaz web y navegación](#️-interfaz-web-y-navegación)
18. [Sistema de ayuda (F1)](#-sistema-de-ayuda-f1)
19. [Integraciones externas](#-integraciones-externas)
20. [Roles y permisos](#-roles-y-permisos)
21. [Despliegue en producción](#-despliegue-en-producción)
22. [Operación y mantenimiento](#-operación-y-mantenimiento)
23. [Solución de problemas](#-solución-de-problemas)
24. [Glosario](#-glosario)
25. [Changelog](#-changelog)

---

# 🎯 Descripción general

**Comfutech Monitor** es un sistema de monitoreo de red que resuelve la problemática de la empresa Comfutech en Güigüe: la ausencia de un NMS centralizado que consolidara las métricas de sus equipos de red.

## Problema que resuelve

- **Antes:** verificación manual equipo por equipo, detección de fallas solo por reclamos.
- **Después:** panel web centralizado con métricas en tiempo real, alertas automáticas multi-grupo, notificaciones**Fabricantes:** MikroTik, Cisco, Huawei, Ubiquiti, Cambium, Mimosa, TP-Link y EnGenius.
- **Métricas de tráfico:** capacidad, Rx/Tx y utilización por interfaz.
- **Métricas de chasis:** CPU, memoria, temperatura y uptime.
- **Disponibilidad:** latencia ICMP, pérdida de paquetes y puertos TCP.
- **Radiofrecuencia:** señal, CCQ, ruido, tasas TX/RX y airMAX.
- **Clientes AP:** lista de clientes conectados con métricas en vivo.
- **Alertas:** 1-5 grupos de 1-5 condicionales con operadores AND/OR/XOR/NOT.
- **Backups:** manuales y automáticos diarios.

## Beneficios medibles

| Antes | Después |
|--------|----------|
| Verificación manual equipo por equipo | Monitoreo automático cada 60 s |
| Detección de fallas por reclamos | Alertas proactivas |
| Sin visibilidad histórica | Dashboards con retención de 90 días |
| Sin notificaciones automáticas | Telegram en menos de 30 s |
| Sin backups programados | Backup automático diario |
| Configuración en base de datos | Configuración centralizada en TOML |
| Sin acceso de emergencia | Django Admin exclusivo para superadministradores |

---

# 📜 Historia del proyecto

## Fase 1 — Prototipo en C++ (descontinuado)

CRUD de escritorio desarrollado en **C++ con Visual Studio 2015**.

Archivado en:

```text
_legacy/
```

## Fase 2 — Reingeniería en Django (actual)

| Iteración | Cambios principales |
|-----------|--------------------|
| **v0.1** | Setup inicial, Django, apps, modelos y MySQL |
| **v0.2** | Inventario, CRUD de equipos e interfaces |
| **v0.3** | Pollers SNMP, ICMP, Health, InfluxDB y APScheduler |
| **v0.4** | Sistema de alertas |
| **v0.5** | Configuración centralizada |
| **v0.6** | Autenticación y roles |
| **v0.7** | Recuperación de contraseña |
| **v0.8** | Alertas v1 |
| **v0.9** | DeviceModel e is_wireless_link |
| **v1.0** | Refactor completo de la UI |
| **v2.0** | Configuración UI v2 |
| **v3.0** | TOML, mantenimiento, backups, alertas v2, Django Admin y sistema de ayuda |

**Estado actual:** v3.0, producción estable.

---
# 🏗️ Arquitectura del sistema

```text
┌──────────────────────────────────────────────────────────────────┐
│                     NAVEGADOR WEB (Cliente)                      │
│                                                                  │
│ Login · Dashboard · Equipos · Modelos · Interfaces · Alertas     │
│ Reglas · Monitor · Usuarios · Configuración · Mantenimiento      │
│ Django Admin (solo superadmin) · Grafana (enlace externo)        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               │ HTTP (8000)
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│             DJANGO 4.2 + WAITRESS (Servicio Windows)             │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │ Autenticación    │  │ CRUD (ORM)       │  │ Configuración   │ │
│  │ Login / Logout   │  │ Equipos          │  │ TOML Runtime    │ │
│  │ Roles            │  │ Alertas          │  │ Test endpoints  │ │
│  │ Perfiles         │  │ Usuarios         │  │                 │ │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘ │
│                                                                  │
│  Context Processors:                                             │
│  • grafana_available                                             │
│  • is_admin                                                      │
│  • theme                                                         │
│                                                                  │
│  Breadcrumbs automáticos                                         │
│  Sistema de ayuda F1                                             │
└─────────────┬──────────────────────────┬─────────────────────────┘
              │                          │
              │ ORM                     │ Servicios internos
              ▼                          ▼

┌───────────────────────────┐    ┌──────────────────────────────┐
│       MySQL 5.7 / 8.0     │    │     Monitor APScheduler      │
├───────────────────────────┤    ├──────────────────────────────┤
│ auth_user                │    │ Traffic Poller              │
│ devices                  │    │ Health Poller               │
│ device_models            │    │ ICMP/TCP Poller             │
│ interfaces               │    │ Radio Poller                │
│ alert_rules              │    │ AP Clients Poller           │
│ alerts                   │    │ Heartbeat Poller            │
│ email_verifications      │    │ Backup automático           │
│ password_reset_codes     │    └──────────────────────────────┘
│ password_reset_attempts  │
│ monitor_status           │    ┌──────────────────────────────┐
│ discovery_jobs           │    │   Motor de Alertas v2       │
└───────────────────────────┘    │ • 1-5 grupos                │
                                 │ • 1-5 condiciones/grupo     │
                                 │ • AND / OR / XOR / NOT      │
                                 │ • Warm-up 120 s             │
                                 └──────────────────────────────┘

            ┌────────────────────┬────────────────────┐
            ▼                    ▼                    ▼

 ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐
 │ InfluxDB 2.9.1   │  │ config.toml      │  │ backup/      │
 │ metricas_red     │  │ system.toml      │  │ *.sql.gz     │
 │ retención 90 d   │  │ Dynaconf         │  │ *.zip        │
 └─────────┬────────┘  └──────────────────┘  └──────────────┘
           │
           ▼

 ┌─────────────────────────┐
 │     Grafana OSS 10.x    │
 │   Dashboards en vivo    │
 └─────────────────────────┘

         Integraciones externas:
         • Telegram Bot API
         • SMTP
```

## Componentes principales

| Componente | Rol | Servicio | Puerto |
|------------|------|-----------|---------|
| **Django + Waitress** | Backend web, ORM e interfaz | `ComfutechDjango` | 8000 |
| **APScheduler** | Scheduler de polling | `ComfutechMonitor` | — |
| **MySQL** | Base de datos relacional | `MySQL80` | 3306 |
| **InfluxDB 2.9** | Base de datos temporal | `influxdb` | 8086 |
| **Grafana** | Visualización | `grafana` | 3000 |
| **Telegram Bot API** | Notificaciones | Externo | 443 |
| **SMTP** | Email transaccional | Externo | 587/465 |
| **NSSM** | Servicios Windows | Ejecutable | — |
| **Dynaconf + tomlkit** | Gestión de TOML | Librería | — |

---

# 🛠️ Stack tecnológico

## Backend

| Tecnología | Versión | Rol |
|------------|----------|------|
| **Python** | 3.11+ (probado en 3.13) | Runtime |
| **Django** | 4.2 LTS / 5.x | Framework web |
| **Waitress** | 2.x | Servidor WSGI |
| **APScheduler** | 3.10+ | Scheduler |
| **pysnmp** | 7.1+ | Cliente SNMP |
| **influxdb-client** | 1.44+ | Cliente InfluxDB |
| **Dynaconf** | 3.2+ | Configuración TOML |
| **tomlkit** | 0.12+ | Escritura TOML |
| **mysqlclient / pymysql** | 2.2+ / 1.1+ | MySQL |
| **requests** | 2.32+ | APIs externas |
| **openpyxl** | 3.1+ | Exportación Excel |
| **reportlab** | 4.2+ | Exportación PDF |

## Frontend

| Tecnología | Versión | Rol |
|------------|----------|------|
| **Bootstrap** | 5.3.x | Framework CSS |
| **Bootstrap Icons** | 1.11.x | Iconografía |
| **JavaScript** | ES2020+ | Interactividad |
| **Django Templates** | N/A | Renderizado servidor |

## Bases de datos

| Base | Versión | Rol |
|--------|----------|------|
| **MySQL** | 5.7+ / 8.0 | Inventario, usuarios y alertas |
| **InfluxDB** | 2.9.1+ | Métricas temporales |
| **config.toml** | N/A | Configuración runtime |
| **system.toml** | N/A | Bootstrap Django |

## Despliegue

| Herramienta | Rol |
|-------------|-----|
| **NSSM 2.24+** | Servicios Windows |
| **Windows** | 10/11 o Server 2016+ |

---

# ✨ Características principales

## 🧩 Gestión de inventario

### Equipos (`devices`)

- Nombre e IP única.
- Tipo y rol.
- Fabricante y modelo.
- Configuración SNMP v1/v2c/v3.
- Puertos TCP.
- `monitor_interfaces`
- `monitor_health`
- `dashboard_interface`
- Importación y exportación JSON.
- Paginación de 10 registros.

### Modelos de equipos (`device_models`)

- Fabricante.
- Nombre.
- Descripción.
- `oids` (JSON de métricas de chasis).
- `radio_oids` (JSON de radiofrecuencia).
- `has_interfaces`
- `is_wireless_link`
- Editor visual de OIDs.
- JSON avanzado.
- Importación y exportación masiva.

### Interfaces (`interfaces`)

Descubiertas mediante SNMP Walk.

Campos principales:

```text
if_index
if_name
if_alias
if_speed_bps
if_type
admin_status
oper_status
monitored
```

Características:

- Interfaz destacada ⭐.
- Detección rápida de WAN.
- Persistencia del monitoreo tras nuevos discoveries.

### Clientes AP

Almacenados en:

```python
devices.ap_interfaces
```

Información registrada:

```text
mac
ip
essid
hostname
first_seen
last_seen
```

Características:

- Descubrimiento mediante `ubntWlStatTable`.
- Métricas en vivo desde InfluxDB.
- Conservación de clientes offline.

---

## 📊 Motor de monitoreo

El sistema ejecuta múltiples jobs concurrentes mediante APScheduler.

### 1. SNMP Traffic Poller

- Intervalo configurable (60 s por defecto).
- Contadores de 64 bits.
- Fallback a 32 bits.
- Detección de reboot y wrap.
- Cálculo de utilización.
- Escritura en:

```text
measurement: traffic
```

### 2. Core Health Poller

- CPU.
- Memoria.
- Temperatura.
- Uptime.
- OIDs definidos por modelo.
- Compatibilidad especial con MikroTik y Ubiquiti.

Escritura:

```text
measurement: health
```

### 3. ICMP/TCP Poller

- Ping paralelo.
- Verificación TCP.
- 20 workers concurrentes.
- Cálculo de:
  - Latencia.
  - Pérdida de paquetes.

Escritura:

```text
measurements:
- icmp
- tcp
```

### 4. Radio Poller

Solo dispositivos:

```text
is_wireless_link = true
```

Métricas:

```text
radio_freq
radio_txpower
wl_signal
wl_noise_floor
wl_ccq
wl_tx_rate
wl_rx_rate
airmax_quality
airmax_capacity
chan_width
```

Escritura:

```text
measurement: radio
```

### 5. AP Clients Poller

- Descubrimiento automático de clientes.
- Actualización de `ap_interfaces`.
- Almacenamiento de métricas en vivo.
- Conservación de históricos.

Escritura:

```text
measurement: ap_clients
```

### 6. Heartbeat Poller

- Actualización de `monitor_status`.
- Recarga de configuración TOML.
- Reprogramación automática de jobs.
- Reinicio de warm-up de alertas.

### 7. Backup automático

Configurado mediante:

```toml
[maintenance]
auto_backup_enabled = true
backup_time = "03:00"
```

Características:

- Programación mediante `CronTrigger`.
- Recuperación de ejecuciones perdidas.
- Integración con panel de mantenimiento.

---
# 🗺️ Diagramas de flujo por apartado

## 📦 Flujo — Equipos

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         CREAR EQUIPO                               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────┐
│ 1. Crear o reutilizar MODELO           │
│    Define OIDs y capacidades           │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 2. Crear equipo                        │
│    • Nombre                            │
│    • IP única                          │
│    • Fabricante                        │
│    • Modelo                            │
│    • SNMP v1/v2c/v3                    │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 3. Discovery SNMP                      │
│    • Descubre interfaces               │
│    • Guarda en BD                      │
│    • Conserva monitored                │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 4. Seleccionar interfaces              │
│    • Destacada ⭐                       │
│    • WAN principal                     │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 5. Polling automático                  │
│    • Traffic                           │
│    • Health                            │
│    • ICMP/TCP                          │
│    • RF                               │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 6. Evaluación de alertas               │
│    • Telegram                          │
│    • Auto resolución                   │
└────────────────────────────────────────┘
```

---

## 🧬 Flujo — Modelos de Equipos

```text
┌─────────────────────────────────────────────────────────────────────┐
│                       CREAR MODELO                                 │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────┐
│ 1. Identificación                      │
│    • Fabricante                        │
│    • Nombre                            │
│    • Descripción                       │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 2. Capacidades                         │
│    • has_interfaces                    │
│    • is_wireless_link                  │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 3. OIDs de chasis                      │
│    • CPU                               │
│    • Memoria                           │
│    • Temperatura                       │
│    • Uptime                            │
└────────────────────┬───────────────────┘
                     │
             ¿Wireless Link?
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
        Sí                      No
         │                       │
         ▼                       │
┌────────────────────────────────────────┐
│ 4. Configurar Radio OIDs               │
│    • Señal                             │
│    • Ruido                             │
│    • CCQ                               │
│    • AirMAX                            │
│    • TX / RX                           │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 5. JSON avanzado                       │
│    • Campos adicionales                │
│    • Override de OIDs                  │
└────────────────────┬───────────────────┘
                     │
                     ▼
┌────────────────────────────────────────┐
│ 6. Guardar                             │
│    Disponible para equipos             │
└────────────────────────────────────────┘
```

---

## 🚨 Flujo — Alertas (Consumo)

```text
Traffic Poller
Health Poller
ICMP/TCP Poller
Radio Poller
        │
        ▼
┌──────────────────────────────┐
│ evaluate_metrics()           │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Buscar reglas relacionadas   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Evaluar grupos               │
│ AND / OR / XOR / NOT         │
└──────────────┬───────────────┘
               │
               ▼
       ¿Condición válida?
          │         │
         Sí         No
          │         │
          ▼         ▼
   ¿fire_once?   Resolver
          │       alertas
          ▼
¿Ya fue disparada?
     │       │
    Sí      No
     │       │
   Skip      ▼
        Crear alerta
              │
              ▼
     ¿Telegram activo?
              │
              ▼
         send_alert()
```

---

## 📋 Flujo — Reglas de Alerta

```text
Crear Regla
     │
     ▼
Identificación
(nombre, prioridad)
     │
     ▼
Abrir constructor
de condiciones
     │
     ▼
Añadir grupos
(1 a 5)
     │
     ▼
Añadir condiciones
(1 a 5 por grupo)
     │
     ▼
Validar límites
     │
     ▼
Generar JSON v2
     │
     ▼
Configurar Telegram
     │
     ▼
Guardar regla
```

---

## 👥 Flujo — Usuarios

```text
            GESTIÓN DE USUARIOS

    ┌──────────┬──────────┬──────────┐
    ▼          ▼          ▼
  Crear      Editar    Recuperar
 Usuario    Usuario    Contraseña

    │          │          │
    ▼          ▼          ▼

 Username   Cambios     Verificar
 Email      Perfil      Email

    │          │          │
    ▼          ▼          ▼

 Verificación Invalidar Código de
 Email       Tokens     8 dígitos

    │                     │
    ▼                     ▼

 Confirmar           Validar
 enlace              intentos

    │                     │
    └─────────┬───────────┘
              ▼
      Acceso al sistema
```

---

## ⚙️ Flujo — Configuración

```text
Abrir /configuracion/
         │
         ▼
 Mostrar categorías
         │
         ▼
InfluxDB
Monitor
Telegram
Email
Grafana
         │
         ▼
Modificar valores
         │
         ▼
Guardar
         │
         ▼
Escribir config.toml
         │
         ▼
Crear backup .bak
         │
         ▼
Monitor detecta cambios
         │
         ▼
Recargar configuración
```

---

## 🔧 Flujo — Mantenimiento

```text
Abrir /mantenimiento/
          │
          ▼
Ver estadísticas
          │
          ▼
 ┌────────┼────────┐
 ▼        ▼        ▼
BD     Configs    Full

          │
          ▼

Crear Backup
          │
          ▼

Verificar espacio
          │
          ▼

Comprimir
          │
          ▼

Guardar en backup/
          │
          ▼

Actualizar metadatos
          │
          ▼

Aplicar retención
```

---

# 📁 Estructura del proyecto

```text
comfutech-monitor/
│
├── manage.py
├── requirements.txt
├── README.md
│
├── system.toml
├── system.toml.example
│
├── config.toml
├── config.toml.example
│
├── sistema/
├── core/
├── inventario/
├── alertas/
├── monitoreo/
├── mantenimiento/
│
├── templates/
├── static/
├── docs/
├── logs/
├── backup/
├── scripts/
│
└── python_local/
```

---

# ✅ Requisitos previos

## Software mínimo

| Software | Versión |
|-----------|----------|
| Windows | 10 / 11 / Server 2016+ |
| Python | 3.11+ |
| MySQL | 5.7+ / 8.0 |
| InfluxDB | 2.9.1+ |
| Grafana | 9.x+ |
| NSSM | 2.24+ |

## Cuentas externas

- Telegram Bot.
- Grupo de Telegram.
- Cuenta SMTP.
- Acceso administrativo a MySQL.

---

# 🚀 Instalación paso a paso

## 1. Clonar proyecto

```cmd
cd C:\Users\TuUsuario\Desktop

git clone <url-del-repo> comfutech-monitor

cd comfutech-monitor
```

## 2. Crear entorno virtual

```cmd
python -m venv python_local

python_local\Scripts\activate
```

## 3. Instalar dependencias

```cmd
python -m pip install --upgrade pip

pip install -r requirements.txt
```

## 4. Crear base de datos

```sql
CREATE DATABASE monitoreo_red
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

CREATE USER 'monitor'@'localhost'
IDENTIFIED BY 'TU_PASSWORD_SEGURA';

GRANT ALL PRIVILEGES
ON monitoreo_red.*
TO 'monitor'@'localhost';

FLUSH PRIVILEGES;
```

## 5. Crear archivos TOML

### system.toml

```cmd
copy system.toml.example system.toml

notepad system.toml
```

```toml
[django]
secret_key = "GENERA_UNA_CLAVE_ALEATORIA"
debug = false
allowed_hosts = "localhost,127.0.0.1"

[database]
name = "monitoreo_red"
user = "monitor"
password = "TU_PASSWORD_SEGURA"
host = "127.0.0.1"
port = 3306
```

### config.toml

```cmd
copy config.toml.example config.toml

notepad config.toml
```

## 6. Proteger archivos

### Windows

```cmd
icacls system.toml /inheritance:r /grant:r "%USERNAME%:F"

icacls config.toml /inheritance:r /grant:r "%USERNAME%:F"
```

### Linux

```bash
chmod 600 system.toml config.toml
```

## 7. Migraciones

```bash
python manage.py migrate
```

## 8. Crear roles

```bash
python manage.py setup_roles
```

## 9. Crear superusuario

```bash
python manage.py createsuperuser
```

## 10. Cargar modelos

```bash
python manage.py load_device_models
```

## 11. Recolectar estáticos

```bash
python manage.py collectstatic --no-input
```

## 12. Ejecutar en desarrollo

```bash
python manage.py runserver
```

Abrir:

```text
http://localhost:8000/
```

## 13. Migrar desde versiones anteriores

```bash
python manage.py check
```

o

```bash
python manage.py migrate_config_to_toml --backup-bd
```

---
# ⚙️ Configuración (TOML)

## Filosofía de configuración

El sistema utiliza **dos archivos TOML** claramente diferenciados:

| Archivo | Propósito | Modificación |
|----------|------------|--------------|
| `system.toml` | Configuración de arranque de Django | Manual |
| `config.toml` | Configuración runtime del sistema | UI o manual |

### system.toml

Contiene:

- SECRET_KEY
- DEBUG
- Base de datos
- Backend de correo
- Hosts permitidos
- Configuración de logging

### config.toml

Contiene:

- InfluxDB
- Grafana
- Telegram
- SMTP
- Monitor
- Backups
- Parámetros dinámicos

---

## Ventajas de TOML

| Característica | .env | .ini | .toml |
|----------------|------|------|--------|
| Maneja `#` | ❌ | ❌ | ✅ |
| Maneja `=` dentro del valor | ⚠️ | ❌ | ✅ |
| Soporta espacios | ⚠️ | ⚠️ | ✅ |
| Preserva comentarios | ❌ | ❌ | ✅ |
| Soporta secciones | ❌ | ✅ | ✅ |
| Legibilidad | Media | Media | Alta |

---

## Ejemplos válidos

```toml
[influxdb]
token = "abc123=="

[email]
host_password = "abcd abcd abcd abcd"

[django]
secret_key = "MiPassword#2026"
```

---

## Estructura completa de config.toml

```toml
[influxdb]
url = "http://localhost:8086"
token = ""
org = "comfutech"
bucket = "metricas_red"

[grafana]
url = "http://localhost:3000"

[telegram]
enabled = false
bot_token = ""
chat_id = ""

[monitor]
enabled = true

snmp_poll_interval = 60
health_poll_interval = 120
icmp_poll_interval = 120
radio_poll_interval = 120
ap_clients_poll_interval = 120

[email]
host = "smtp.gmail.com"
port = 587
use_tls = true
use_ssl = false

host_user = ""
host_password = ""

default_from = "Comfutech Monitor <noreply@comfutech.local>"

[maintenance]
auto_backup_enabled = false
backup_time = "03:00"
backup_on_startup = false

backup_db = true
backup_config = true

retention_days = 30
mysql_dump_path = ""

[_meta]
updated_at = ""
updated_by = ""

last_backup_run = ""
last_backup_type = ""
last_backup_filename = ""
```

---

## runtime_config.py

Funciones principales:

```python
get_system_config()

get_influx_config()

get_monitor_config()

get_email_config()

get_telegram_config()

get_maintenance_config()

apply_email_config_to_settings()
```

Características:

- Carga lazy.
- Cache interna.
- Recarga transparente.
- Reduce lecturas de disco.

---

## config_ini.py

Responsabilidades:

### Lectura

```python
Dynaconf(
    settings_files=["config.toml"]
)
```

### Escritura

```python
tomlkit.parse()
tomlkit.dumps()
```

### Seguridad

- Escritura atómica.
- Backup previo.
- Reemplazo seguro.
- Protección contra corrupción.

### Recarga

```python
reload_if_changed()
```

Verifica cambios mediante:

```text
mtime (modification time)
```

---

## Migración automática desde INI

Escenario:

```text
Existe config.ini
No existe config.toml
```

Proceso:

```text
Leer config.ini
      │
      ▼
Convertir a TOML
      │
      ▼
Guardar config.toml
      │
      ▼
Renombrar config.ini
a config.ini.bak
```

Beneficios:

- Sin pérdida de datos.
- Transparente para el usuario.
- Compatible con instalaciones antiguas.

---

# 💾 Base de datos

## Bases utilizadas

### MySQL

Base operacional.

Contiene:

```text
Usuarios
Roles
Equipos
Interfaces
Alertas
Configuración histórica
Monitor
```

### InfluxDB

Base temporal.

Contiene:

```text
Traffic
Health
ICMP
TCP
Radio
AP Clients
```

---

## Tablas principales

### Autenticación Django

```text
auth_user
auth_group
auth_permission
django_session
django_admin_log
```

---

### Inventario

#### device_models

```text
vendor
name

oids
radio_oids

has_interfaces
is_wireless_link

active
```

#### devices

```text
name
ip

device_type
device_role

vendor
device_model_id

location

snmp_*

tcp_ports

monitor_interfaces
monitor_health

dashboard_interface_id

ap_interfaces

active
```

#### interfaces

```text
device_id

if_index
if_name
if_alias

if_speed_bps
if_type

admin_status
oper_status

monitored
```

---

### Alertas

#### alert_rules

```text
name
description

conditionals

severity
custom_message

telegram_enabled
telegram_cooldown_sec

fire_once
skip_on_startup

enabled
```

#### alerts

```text
device_id
interface_id

rule_id

alert_type
severity

message

value_observed
threshold_value

status

created_at
resolved_at
```

---

### Core

#### email_verifications

```text
user_id

verified
verified_at
verified_email

token
token_created_at
```

#### password_reset_codes

```text
user_id

code

created_at
expires_at

used
```

#### password_reset_attempts

```text
user_id

ip

successful
created_at
```

---

### Monitoreo

#### monitor_status

```text
last_heartbeat

status
hostname
pid

last_traffic_run
last_health_run
last_icmp_run
last_radio_run
last_ap_clients_run

last_error
```

#### discovery_jobs

```text
device_id

status

interfaces_*

started_at
finished_at

duration_ms

error_message

triggered_by_id
```

---

## Tablas eliminadas

Las siguientes tablas quedaron obsoletas en la versión 3.0:

```text
system_config
email_config
```

La configuración se almacena ahora en:

```text
config.toml
```

---

# 📈 InfluxDB

## Bucket principal

```text
metricas_red
```

Retención:

```text
90 días
```

---

## Measurements

### traffic

Campos:

```text
in_bps
out_bps

utilization_pct

capacity_bps

rx_octets
tx_octets
```

Tags:

```text
device
ip
interface
role
```

---

### health

Campos:

```text
cpu_pct
mem_pct

temp_c

uptime
```

Tags:

```text
device
ip
role
vendor
```

---

### icmp

Campos:

```text
is_alive

latency_ms

packet_loss_pct
```

Tags:

```text
device
ip
role
```

---

### tcp

Campos:

```text
is_open
```

Tags:

```text
device
ip
role
port
```

---

### radio

Campos:

```text
radio_freq
radio_txpower

wl_signal
wl_noise_floor

wl_ccq

wl_tx_rate
wl_rx_rate

airmax_quality
airmax_capacity

chan_width
```

Tags:

```text
device
ip
role
vendor
```

---

### ap_clients

Campos:

```text
signal_dbm
noise_dbm

ccq_pct

tx_rate_bps
rx_rate_bps

snr_db
```

Tags:

```text
ap_device
ap_ip

client_mac
client_ip

essid

if_index
```

---

# 📊 Motor de monitoreo

## Servicios

| Servicio | Archivo | Función |
|-----------|----------|----------|
| Cliente SNMP | `snmp_client.py` | Wrapper pysnmp |
| Discovery | `discovery.py` | Descubrimiento SNMP |
| Traffic | `traffic.py` | Tráfico de interfaces |
| Health | `health.py` | Métricas de chasis |
| ICMP/TCP | `icmp_tcp.py` | Disponibilidad |
| Radio | `radio.py` | Métricas RF |
| AP Clients | `ap_clients.py` | Clientes inalámbricos |
| Alerts | `alerts.py` | Motor de alertas |
| Telegram | `telegram.py` | Notificaciones |
| Influx Writer | `influx_writer.py` | Escritura |
| Influx Reader | `influx_reader.py` | Consultas |

---

## Comandos de administración

### Monitor

```bash
python manage.py run_monitor
```

Modo silencioso:

```bash
python manage.py run_monitor --silent
```

Sin discovery inicial:

```bash
python manage.py run_monitor --skip-discovery
```

---

### Ejecución única

```bash
python manage.py poll_once
```

Específica:

```bash
python manage.py poll_once --only traffic

python manage.py poll_once --only health

python manage.py poll_once --only icmp

python manage.py poll_once --only radio

python manage.py poll_once --only ap_clients
```

---

### Pollers individuales

```bash
python manage.py poll_snmp

python manage.py poll_health

python manage.py poll_icmp

python manage.py poll_radio

python manage.py poll_ap_clients
```

---

### Validación

```bash
python manage.py validate_radio_oids <IP>

python manage.py validate_ap_clients <IP>
```

---

### Utilidades

```bash
python manage.py setup_roles

python manage.py load_device_models

python manage.py migrate_config_to_toml --backup-bd
```

---
# 🚨 Sistema de alertas v2 (Grupos + Operadores)

## Estructura JSON

Cada regla puede contener:

- Entre 1 y 5 grupos.
- Entre 1 y 5 condicionales por grupo.
- Máximo 10 condicionales totales.

Ejemplo:

```json
{
  "version": 2,
  "groups": [
    {
      "logic": null,
      "negate": false,
      "operators": ["AND"],
      "conditionals": [
        {
          "device_id": 1,
          "metric": "cpu_pct",
          "operator": "gte",
          "threshold": 85,
          "duration_sec": 60,
          "negate": false
        },
        {
          "device_id": 1,
          "metric": "mem_pct",
          "operator": "gte",
          "threshold": 90,
          "duration_sec": 60,
          "negate": false
        }
      ]
    },
    {
      "logic": "OR",
      "negate": true,
      "conditionals": [
        {
          "device_id": 2,
          "metric": "device_down",
          "operator": "eq",
          "threshold": 0,
          "duration_sec": 120,
          "negate": false
        }
      ]
    }
  ]
}
```

Semántica:

```text
(cond1 AND cond2) OR NOT(cond3)
```

---

## Operadores soportados

### Entre grupos

```text
AND
OR
XOR
```

### Entre condicionales

```text
AND
OR
XOR
```

### Negación

A nivel de grupo:

```text
NOT(grupo)
```

A nivel de condición:

```text
NOT(condición)
```

---

## Métricas disponibles

### Disponibilidad

```text
device_down
latency_ms
packet_loss_pct
is_open
```

### Tráfico

```text
utilization_pct
in_bps
out_bps
```

### Chasis

```text
cpu_pct
mem_pct
temp_c
uptime
```

### Radio

```text
wl_signal
wl_noise_floor
wl_ccq

wl_tx_rate
wl_rx_rate

airmax_quality
airmax_capacity
```

---

## Placeholders soportados

```text
{rule_name}

{severity}

{timestamp}

{conditionals_count}
{groups_count}

{device}
{ip}

{metric}
{value}
{threshold}

{device1}
{device2}
...
{device10}
```

---

## Máquina de estados

```python
_cond_states[
    (rule_id, group_index, cond_index)
] = {
    "first_seen": timestamp,
    "last_value": float
}
```

---

## Warm-up

Duración:

```text
120 segundos
```

Comportamiento:

```text
Monitor inicia
      │
      ▼
Warm-up activo
      │
      ▼
Reglas con
skip_on_startup=True

NO se evalúan
```

---

## Auto-resolución

```text
Condición TRUE
      │
      ▼
Alerta activa
      │
      ▼
Condición deja de cumplirse
      │
      ▼
Alerta resuelta automáticamente
```

---

# 👥 Sistema de usuarios

## Creación de usuarios

### Restricciones

#### Username

```text
3 - 150 caracteres

Permitido:
a-z
A-Z
0-9
.
_
-
```

No se permiten:

```text
Espacios
Caracteres especiales
```

---

#### Nombre y apellido

Permitido:

```text
Letras
Espacios
Guiones
Apóstrofes
```

---

#### Email

```text
Obligatorio
Único
Validado
```

---

#### Contraseña

```text
8 a 16 caracteres
```

Validaciones:

```text
Longitud mínima
Complejidad
Confirmación
```

---

## Verificación de email

Proceso:

```text
Crear usuario
      │
      ▼
Enviar email
      │
      ▼
Abrir enlace
      │
      ▼
Verificado = True
```

Validez:

```text
48 horas
```

---

## Recuperación de contraseña

### Requisitos

```text
Email verificado
```

### Código

```text
8 dígitos
```

Validez:

```text
5 minutos
```

---

### Protección anti fuerza bruta

```text
Máximo:
5 intentos

Ventana:
15 minutos
```

---

## Restricciones de seguridad

### Roles

```text
Nadie puede cambiar
su propio rol
```

### Superadministrador

```text
No puede eliminarse
el último superadmin
```

### Administradores

```text
No pueden ver
otros administradores
```

### Usuario admin

```text
No puede eliminarse
```

---

# 🔧 Panel de mantenimiento (Backups)

## Backups manuales

### Base de datos

```text
db_YYYY-MM-DD_HH-MM-SS.sql.gz
```

### Configuración

```text
config_YYYY-MM-DD_HH-MM-SS.zip
```

Contenido:

```text
config.toml
system.toml
```

### Completo

```text
full_YYYY-MM-DD_HH-MM-SS.zip
```

Contenido:

```text
Base de datos
Configuración
manifest.json
```

---

## Backups automáticos

Configuración:

```toml
[maintenance]

auto_backup_enabled = true

backup_time = "03:00"

backup_on_startup = false

backup_db = true
backup_config = true

retention_days = 30
```

---

## Política de retención

Ejemplo:

```text
retention_days = 30
```

Comportamiento:

```text
Backup > 30 días
         │
         ▼
Eliminado automáticamente
```

---

## Seguridad

### Directorios

```text
backup/
Permisos 0700
```

### Archivos

```text
Permisos 0600
```

### Base de datos

```text
mysqldump
--defaults-extra-file
```

Ventaja:

```text
Credenciales no visibles
en procesos del sistema
```

---

## Protección adicional

```text
Validación estricta de nombres
Sin path traversal
```

```text
Bloqueo de concurrencia
```

```text
Comprobación de espacio libre
```

Mínimo:

```text
100 MB
```

---

## Restauración

### Base de datos

```bash
gunzip < db_xxx.sql.gz | mysql -u USER -p DB_NAME
```

### Configuración

```text
Descomprimir ZIP
```

Copiar:

```text
config.toml
system.toml
```

a:

```text
raíz del proyecto
```

---

# 🛡️ Django Admin

## Acceso

URL:

```text
/django-admin/
```

No se utiliza:

```text
/admin/
```

---

## Control de acceso

Solo:

```python
is_superuser=True
```

Los administradores normales:

```text
NO tienen acceso
```

---

## Disponible en producción

```text
Sí
```

No depende de:

```python
DEBUG=True
```

---

## Modelos registrados

### Alertas

```text
Alert
AlertRule
```

---

### Core

```text
EmailVerification

PasswordResetCode

PasswordResetAttempt
```

---

### Inventario

```text
DeviceModel

Device

Interface
```

---

### Monitoreo

```text
DiscoveryJob

MonitorStatus
```

---

## Branding

Título:

```text
Comfutech Monitor — Administración
```

Botón:

```text
Ver sitio
```

Destino:

```text
/
```

---

# 🖥️ Interfaz web y navegación

## URLs principales

| URL | Descripción | Permiso |
|------|-------------|----------|
| `/` | Dashboard | Autenticado |
| `/accounts/login/` | Login | Público |
| `/setup/` | Setup inicial | Público |
| `/equipos/` | Equipos | Autenticado |
| `/equipos/modelos/` | Modelos | Autenticado |
| `/alertas/` | Alertas | Autenticado |
| `/alertas/reglas/` | Reglas | Autenticado |
| `/monitoreo/status/` | Estado monitor | Autenticado |
| `/monitoreo/live/` | Monitor en vivo | Autenticado |
| `/usuarios/` | Usuarios | Administrador |
| `/perfil/` | Perfil | Autenticado |
| `/configuracion/` | Configuración | Superadmin |
| `/mantenimiento/` | Backups | Superadmin |
| `/django-admin/` | Django Admin | Superadmin |

---

## Sidebar principal

```text
Dashboard

Equipos
 ├─ Ver todos
 ├─ Nuevo
 └─ Modelos

Alertas

Reglas
 ├─ Ver todas
 └─ Nueva

Monitor
 ├─ Estado
 └─ En vivo

Configuraciones
 ├─ Usuarios
 ├─ Configuración
 └─ Mantenimiento

Grafana
```

---

## Footer del sidebar

```text
Perfil

Cambiar contraseña

Cerrar sesión

Modo claro

Modo oscuro

Modo automático

Ayuda (F1)
```

---

## Theme Switcher

Modos:

```text
Claro

Oscuro

Automático
```

Persistencia:

```javascript
localStorage
```

Ventajas:

```text
Sin parpadeo visual
al cargar la página
```

---

# 📖 Sistema de ayuda (F1)

## Funcionamiento

```text
F1
Shift + ?
Botón Ayuda
```

abren:

```text
Modal global de ayuda
```

---

## API de ayuda

```javascript
registerHelpContent({
    title: "Título",
    sections: [
        {
            heading: "Sección",
            body: "Contenido HTML",
            list: [
                "Elemento 1",
                "Elemento 2"
            ]
        }
    ]
});
```

---

## Páginas soportadas

```text
Dashboard

Equipos

Modelos

Interfaces

Alertas

Reglas

Usuarios

Perfil

Monitor

Configuración

Mantenimiento
```

---
# 🔌 Integraciones externas

## InfluxDB 2.9

### Funcionalidades

- Almacenamiento de métricas.
- Series temporales.
- Retención de 90 días.
- Fuente de datos para Grafana.

### Configuración

```toml
[influxdb]
url = "http://localhost:8086"
token = ""
org = "comfutech"
bucket = "metricas_red"
```

### Características

```text
Cliente compartido

Timeout: 5 segundos

Reconexión automática

Recarga dinámica al cambiar config.toml
```

---

## Grafana OSS

### Uso

```text
Visualización de métricas
Dashboards históricos
Gráficas en tiempo real
```

### Data Source

```text
InfluxDB + Flux
```

### Dashboard de referencia

```text
docs/grafana-dashboard.json
```

### Configuración

```toml
[grafana]
url = "http://localhost:3000"
```

### Verificación

```text
Context Processor

grafana_available
```

Realiza comprobaciones periódicas para mostrar u ocultar el acceso rápido.

---

## Telegram Bot API

### Funciones

```text
Notificaciones de alertas

Respuestas automáticas

Pruebas desde UI
```

### Configuración

```toml
[telegram]
enabled = true

bot_token = "TOKEN"

chat_id = "-1000000000"
```

### Características

```text
Mensajes HTML

Cooldown configurable

Pruebas desde configuración

Notificaciones en tiempo real
```

### Flujo

```text
Alerta
   │
   ▼
Motor Alertas
   │
   ▼
Telegram
   │
   ▼
Grupo de operaciones
```

---

## SMTP

### Proveedores compatibles

```text
Gmail

Office365

Exchange

SMTP estándar
```

### Configuración

```toml
[email]
host = "smtp.gmail.com"

port = 587

use_tls = true

host_user = ""

host_password = ""
```

### Funciones

```text
Verificación de correo

Recuperación de contraseña

Notificaciones futuras
```

---

# 👥 Roles y permisos

## Roles ofíciales

| Rol | is_superuser | is_staff | Grupo |
|-------|-------------|-----------|--------|
| Superadministrador | ✅ | ✅ | Ninguno |
| Administrador | ❌ | ✅ | Administrador |
| Usuario | ❌ | ❌ | Usuario |

---

## Matriz de permisos

| Acción | Superadmin | Administrador | Usuario |
|----------|------------|----------------|----------|
| Dashboard | ✅ | ✅ | ✅ |
| Equipos | ✅ | ✅ | ✅ |
| Ver Alertas | ✅ | ✅ | ✅ |
| Crear Equipos | ✅ | ✅ | ❌ |
| Editar Equipos | ✅ | ✅ | ❌ |
| Crear Reglas | ✅ | ✅ | ❌ |
| Resolver Alertas | ✅ | ✅ | ❌ |
| Gestionar Usuarios | ✅ | ✅ | ❌ |
| Cambiar Email de Otros | ✅ | ❌ | ❌ |
| Configuración | ✅ | ❌ | ❌ |
| Backups | ✅ | ❌ | ❌ |
| Django Admin | ✅ | ❌ | ❌ |

---

## Jerarquía

```text
Superadministrador
        │
        ▼
Administrador
        │
        ▼
Usuario
```

---

# 🚀 Despliegue en producción

## Arquitectura recomendada

```text
                Internet
                    │
                    ▼

              Windows Server

                    │

     ┌──────────────┼──────────────┐

     ▼                             ▼

ComfutechDjango            ComfutechMonitor
 (Waitress)                  (Scheduler)

     ▼                             ▼

              MySQL

     ▼                             ▼

           InfluxDB

     ▼

           Grafana
```

---

## Servicios Windows

Instalación:

```cmd
cd scripts

install_services.bat
```

---

### ComfutechDjango

Ejecuta:

```text
Waitress
Django
```

Puerto:

```text
8000
```

---

### ComfutechMonitor

Ejecuta:

```bash
python manage.py run_monitor --silent
```

---

## Verificación

### Estado del servicio web

```cmd
nssm status ComfutechDjango
```

Resultado esperado:

```text
SERVICE_RUNNING
```

---

### Estado del monitor

```cmd
nssm status ComfutechMonitor
```

Resultado esperado:

```text
SERVICE_RUNNING
```

---

## Actualización completa

```cmd
deploy.bat
```

Proceso:

```text
Migraciones

Estáticos

Reinicio de servicios

Validaciones
```

---

## Configuración recomendada

### system.toml

```toml
[django]

debug = false

allowed_hosts = "localhost,127.0.0.1,10.253.215.X"
```

### config.toml

Ajustar:

```text
Intervalos

Retención

Backups

Telegram

SMTP

Grafana
```

---

# 🔧 Operación y mantenimiento

## Comandos frecuentes

### Migraciones

```bash
python manage.py migrate
```

### Nuevas migraciones

```bash
python manage.py makemigrations
```

### Estáticos

```bash
python manage.py collectstatic
```

### Superusuario

```bash
python manage.py createsuperuser
```

### Shell

```bash
python manage.py shell
```

---

## Supervisión

### Dashboard

```text
/
```

### Estado monitor

```text
/monitoreo/status/
```

### Live Monitor

```text
/monitoreo/live/
```

### Mantenimiento

```text
/mantenimiento/
```

---

## Logs

Ubicación:

```text
logs/
```

Rotación:

```text
5 MB por archivo

3 archivos históricos
```

Implementación:

```python
RotatingFileHandler
```

---

## Backups

### Manuales

Desde:

```text
/mantenimiento/
```

o

```bash
mysqldump -u monitor -p monitoreo_red > backup.sql
```

### Automáticos

Gestionados por:

```text
APScheduler
```

---

# 🐛 Solución de problemas

## El monitor no arranca

Verificar:

```cmd
nssm status ComfutechMonitor
```

Comprobar:

```text
logs/monitor_err.log
```

Validar:

```bash
python manage.py check
```

---

## No llegan mensajes de Telegram

Verificar:

```text
telegram_enabled = true
```

Comprobar:

```text
Bot dentro del grupo

Chat ID válido

Token correcto
```

Realizar:

```text
Prueba de notificación
```

---

## Las alertas no disparan

Verificar:

```text
enabled = true
```

```text
La regla contiene condiciones
```

```text
duration_sec suficiente
```

```text
El warm-up terminó
```

```text
fire_once no bloquea eventos
```

---

## Problemas con TOML

Ejemplo incorrecto:

```toml
password = myPass#2026
```

Resultado:

```text
#2026 es tomado como comentario
```

Correcto:

```toml
password = "myPass#2026"
```

---

## Error al guardar config.toml

Verificar:

```text
Permisos

Espacio en disco

config.toml.bak

logs/django.log
```

---

## mysqldump no encontrado

Soluciones:

```text
Agregar al PATH
```

o

```text
Configurar ruta manual
```

desde:

```text
/mantenimiento/
```

---

## Backups fallan

Verificar:

```text
Espacio libre > 100 MB
```

Aplicar:

```text
retention_days
```

o eliminar backups viejos.

---

# 📚 Glosario

| Término | Definición |
|----------|------------|
| SNMP | Simple Network Management Protocol |
| OID | Object Identifier |
| MIB | Management Information Base |
| ICMP | Internet Control Message Protocol |
| NMS | Network Management System |
| QoS | Quality of Service |
| SLA | Service Level Agreement |
| MTTR | Mean Time To Repair |
| TOML | Tom's Obvious Minimal Language |
| Dynaconf | Librería de configuración |
| tomlkit | Escritura avanzada de TOML |
| APScheduler | Scheduler para Python |
| ifIndex | Índice único de interfaz SNMP |
| Counter Wrap | Desbordamiento de contador |
| NSSM | Non-Sucking Service Manager |

---

# 📝 Changelog

## v3.0 — Octubre 2026

### Configuración TOML

- Migración de `config.ini` a `config.toml`.
- Migración de `.env` a `system.toml`.
- Dynaconf + tomlkit.
- Escritura atómica.
- Recarga automática.

### Eliminación de modelos obsoletos

Eliminados:

```text
SystemConfig

EmailConfig
```

---

### Nueva aplicación mantenimiento

Incluye:

```text
Backups manuales

Backups automáticos

Retención

Restauración

Integración con APScheduler
```

---

### Restauración de Django Admin

Características:

```text
Branding propio

Control por superusuario

Registro completo de modelos

Disponible en producción
```

---

### Alertas v2

Novedades:

```text
Grupos

Operadores lógicos

NOT

Editor visual

Migración automática
```

---

### Nuevos Pollers

```text
Radio

Clientes AP
```

---

### Dashboard

```text
Selector timeframe

Sparklines

Toasts

Discovery rápido

Interfaz destacada
```

---

### Sistema de ayuda

```text
F1

Shift + ?

registerHelpContent()
```

---

### Breadcrumbs

```text
AutoBreadcrumb

Mapping centralizado

Enriquecimiento automático
```

---

### Mejoras UI

```text
Sidebar

Configuración

Alertas

Usuarios

Equipos

Modelos
```

---

### Correcciones

```text
Roles

Rule Builder

JSON Script

Ubiquiti OIDs

airOS 8.x
```

---

## v2.0

```text
Configuración UI v2

Alertas v1

Navbar lateral

Theme Switcher
```

---

## v1.0

```text
Primera versión estable
```

---

## v0.1 – v0.9

```text
Iteraciones incrementales
```

---

# 📄 Licencia

```text
Uso interno de Comfutech.

Todos los derechos reservados.
```

---

# 👥 Autores

```text
Victor
Desarrollo del sistema
```

```text
Comfutech
Operación y requisitos
```

Ubicación:

```text
Güigüe
Estado Carabobo
Venezuela
```

---

# 🔗 Enlaces de interés

- Django Documentation
- PySNMP Documentation
- InfluxDB Documentation
- Dynaconf Documentation
- TOML Specification
- Grafana Documentation
- APScheduler Documentation
- NSSM Documentation
- Telegram Bot API

---

**Última actualización:** Octubre 2026

**Versión del sistema:** 3.0

**Estado:** Producción

---

# 📋 Resumen de cambios en el README

| Sección | Cambio |
|----------|---------|
| Versión | 2.0 → 3.0 |
| Stack | Dynaconf + tomlkit |
| Arquitectura | TOML + backups |
| Diagramas | Nuevos diagramas ASCII |
| Alertas | Sistema v2 por grupos |
| Mantenimiento | Nueva aplicación |
| Django Admin | Restaurado |
| Usuarios | Mejoras y estadísticas |
| Configuración | Migración a TOML |
| Glosario | Nuevos conceptos |
| Changelog | Actualizado a v3.0 |

---