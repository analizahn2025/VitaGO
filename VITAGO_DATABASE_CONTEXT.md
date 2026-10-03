# DATABASE_CONTEXT.md

> Actualización vigente (2026-10-01): `vehiculos.capacidad_carga_kg` se
> conserva nullable solo por compatibilidad/historia; no se edita en la API.
> Los tipos de vehículo distintos de `MOTOCICLETA` se conservan para
> trazabilidad, no para nuevas altas. `repartidores.capacidad` es una copia
> derivada del conteo de solicitudes activas, no un dato de entrada. Se añade
> `notificaciones_usuario`, vinculada a usuario, solicitud y evento, con fecha
> de lectura y unicidad por usuario/evento.

## 0. Identidad del producto

- Plataforma: **VitaGo**.
- Base interna: **VitaGo Corporate**.
- Base externa: **VitaGo Network**.
- Ambas bases son PostgreSQL independientes y siguen el mismo esquema/migraciones siempre que sea posible.

### Convención de idioma vigente

Las tablas, columnas, modelos, estados, índices y restricciones creados por VitaGo deben nombrarse en español. Los nombres en inglés de los esquemas conceptuales incluidos más adelante describen la intención funcional original y deben traducirse al momento de implementarse. Solo permanecen en inglés los términos impuestos por PostgreSQL, Django o estándares externos.

Mapeo inicial aprobado:

```text
countries          -> paises
companies          -> empresas
branches           -> sucursales
location_types     -> tipos_ubicacion
locations          -> ubicaciones
company_locations  -> ubicaciones_empresa
users              -> usuarios
```


## 1. Motor

Usar PostgreSQL puro.

Habrá dos bases físicamente separadas:

- PostgreSQL Corporate
- PostgreSQL External

Ambas deben seguir, en lo posible, el mismo esquema y las mismas migraciones.

Esto permite mantener un solo código y una sola evolución de esquema desde `main`.

Corporate puede tener tablas o columnas no utilizadas, pero no se recomienda crear dos modelos incompatibles.

---

## 2. Principio general

Mismo esquema lógico:

```text
main
  ↓
migrations
  ↓
Corporate DB
External DB
```

No compartir datos entre bases.

No crear claves foráneas entre bases.

No depender de sincronización automática entre ellas.

---

## 3. Extensiones recomendadas

Considerar:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Para UUID si se desea.

Para geodatos, evaluar PostGIS:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

PostGIS es especialmente útil para:
- distancia a ruta;
- proximidad;
- geofencing;
- búsquedas espaciales;
- análisis de GPS.

Si no se usa PostGIS inicialmente, diseñar para poder migrar.

---

## 4. Convenciones

- PK principal: UUID para entidades de negocio.
- GPS/pings: puede usar `BIGINT` por volumen.
- timestamps con timezone.
- `created_at`
- `updated_at`
- soft delete o `status`, no borrado destructivo para datos operativos.
- índices en FKs, timestamps y campos de búsqueda frecuentes.
- nombres en `snake_case`.

---

## 5. countries

```text
countries
---------
id UUID PK
iso2 VARCHAR(2) UNIQUE
iso3 VARCHAR(3)
name VARCHAR
phone_code VARCHAR
currency_code VARCHAR(3)
timezone_default VARCHAR
is_active BOOLEAN
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

Implementación vigente en español:

- `vehiculos`: UUID, `empresa_id` opcional, `placa` única, `tipo`, `marca`,
  `modelo`, `anio`, `capacidad_carga_kg`, `estado`, `notas` y marcas de tiempo;
- restricciones para tipos, estados y capacidad de carga positiva;
- índices por empresa/estado y estado;
- Corporate utiliza `empresa_id`; Network conserva `empresa_id = NULL` para
  representar el alcance global;
- kilometraje y mantenimiento permanecen pendientes para su fase específica.

---

## 6. companies

```text
companies
---------
id UUID PK
name VARCHAR
legal_name VARCHAR NULL
tax_id VARCHAR NULL
phone VARCHAR NULL
email VARCHAR NULL
country_id UUID FK -> countries
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

Corporate probablemente tendrá una empresa principal.

External tendrá múltiples empresas.

---

## 7. location_types

```text
location_types
--------------
id UUID PK
code VARCHAR UNIQUE
name VARCHAR
is_active BOOLEAN
```

Ejemplos:
- HOSPITAL
- CLINIC
- LAB
- OFFICE
- PHARMACY
- BLOOD_BANK
- IMAGING_CENTER
- BRANCH
- RESIDENCE
- OTHER

---

## 8. locations

```text
locations
---------
id UUID PK
name VARCHAR
location_type_id UUID FK

source VARCHAR
google_place_id VARCHAR NULL

country_id UUID FK
admin_level_1 VARCHAR NULL
admin_level_2 VARCHAR NULL
locality VARCHAR NULL
neighborhood VARCHAR NULL

address TEXT
latitude NUMERIC(9,6)
longitude NUMERIC(9,6)

phone VARCHAR NULL
contact_name VARCHAR NULL
opening_hours JSONB NULL
instructions TEXT NULL

is_verified BOOLEAN DEFAULT FALSE
status VARCHAR

created_by UUID NULL
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

`source`:
- GOOGLE
- USER_REGISTERED

Si se usa PostGIS, agregar un `geography(Point, 4326)`.

Implementación vigente en español:

- `nivel_administrativo_1` conserva internamente el departamento;
- `nivel_administrativo_2` conserva internamente el municipio;
- `localidad` conserva internamente la ciudad;
- `colonia` conserva la colonia, barrio o sector específico;
- la API traduce los tres primeros a `departamento`, `municipio` y `ciudad`;
- los cuatro campos son opcionales para permitir direcciones incompletas de
  distintas fuentes y países.

---

## 9. branches

```text
branches
--------
id UUID PK
company_id UUID FK -> companies
name VARCHAR
code VARCHAR NULL
location_id UUID FK -> locations
phone VARCHAR NULL
email VARCHAR NULL
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

---

## 10. company_locations

Controla qué lugares puede usar una empresa.

```text
company_locations
-----------------
id UUID PK
company_id UUID FK
location_id UUID FK
is_origin_allowed BOOLEAN
is_destination_allowed BOOLEAN
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ

UNIQUE(company_id, location_id)
```

Esta tabla permite que un mismo hospital/laboratorio sea utilizado por varias empresas sin duplicar la ubicación.

---

## 11. users - Corporate

En Corporate NO guardar contraseña.

```text
users
-----
id UUID PK
external_auth_id VARCHAR UNIQUE NOT NULL
first_name VARCHAR
last_name VARCHAR
email VARCHAR
phone VARCHAR NULL
company_id UUID NULL
branch_id UUID NULL
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

---

## 12. users - External

Para mantener esquema común puede existir la misma tabla con campos opcionales adicionales.

```text
users
-----
id UUID PK
external_auth_id VARCHAR NULL
first_name VARCHAR
last_name VARCHAR
email VARCHAR UNIQUE
phone VARCHAR NULL
password_hash TEXT NULL
company_id UUID NULL
branch_id UUID NULL
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

Regla:

- Corporate: `password_hash IS NULL`
- External: puede usar `password_hash`

Idealmente controlar esto por backend y constraints parciales según estrategia.

---

## 13. roles

```text
roles
-----
id UUID PK
codigo VARCHAR UNIQUE
nombre VARCHAR
descripcion TEXT NULL
activo BOOLEAN
permite_alcance_global BOOLEAN
permite_alcance_empresa BOOLEAN
permite_alcance_sucursal BOOLEAN
creado_en TIMESTAMPTZ
actualizado_en TIMESTAMPTZ
```

---

## 14. permisos

```text
permisos
--------
id UUID PK
codigo VARCHAR UNIQUE
nombre VARCHAR
descripcion TEXT NULL
activo BOOLEAN
creado_en TIMESTAMPTZ
actualizado_en TIMESTAMPTZ
```

---

## 15. permisos_rol

```text
permisos_rol
------------
id UUID PK
rol_id UUID FK
permiso_id UUID FK
activo BOOLEAN
creado_en TIMESTAMPTZ
actualizado_en TIMESTAMPTZ

UNIQUE(rol_id, permiso_id)
```

---

## 16. roles_usuario

```text
roles_usuario
-------------
id UUID PK
usuario_id UUID FK
rol_id UUID FK
tipo_alcance VARCHAR
empresa_id UUID NULL FK
sucursal_id UUID NULL FK
activo BOOLEAN
asignado_por_id UUID NULL FK
asignado_en TIMESTAMPTZ
revocado_por_id UUID NULL FK
revocado_en TIMESTAMPTZ NULL
creado_en TIMESTAMPTZ
actualizado_en TIMESTAMPTZ
```

`tipo_alcance`:

- `GLOBAL`
- `EMPRESA`
- `SUCURSAL`

Las asignaciones revocadas conservan su historial. Solo puede existir una asignación activa por usuario, rol y alcance equivalente.

Catálogo corporativo vigente:

- `GERENTE_OPERACIONES` concentra la coordinación operativa, los envíos
  especiales y la administración de usuarios y roles operativos dentro de una
  empresa;
- sus permisos administrativos adicionales son `usuario.administrar` y
  `rol.asignar`;
- solo puede delegar `SOLICITANTE_CORPORATIVO` y
  `REPARTIDOR_CORPORATIVO`;
- la autorización de servicio impide que modifique administradores u otros
  gerentes aunque compartan la misma empresa;
- `SUPERVISOR_CORPORATIVO` se conserva inactivo para no eliminar referencias
  históricas, pero sus relaciones activas de permisos fueron deshabilitadas.

---

## 17. sesiones_autenticacion

Principalmente External, aunque puede usarse para control local Corporate si conviene.

```text
sesiones_autenticacion
----------------------
id UUID PK
usuario_id UUID FK
hash_token_refresco VARCHAR(64) UNIQUE
identificador_token VARCHAR(64) UNIQUE
familia UUID
identificador_dispositivo VARCHAR NULL
direccion_ip INET NULL
agente_usuario TEXT NULL
creado_en TIMESTAMPTZ
actualizado_en TIMESTAMPTZ
expira_en TIMESTAMPTZ
ultimo_uso_en TIMESTAMPTZ NULL
revocado_en TIMESTAMPTZ NULL
motivo_revocacion VARCHAR NULL
reemplazada_por_id UUID NULL FK -> sesiones_autenticacion
```

Nunca guardar refresh token en texto plano.

La rotación crea una nueva fila y enlaza la anterior mediante
`reemplazada_por_id`. Esto conserva auditoría, permite cierre remoto y detecta
la reutilización de tokens de una misma familia.

---

## 18. vehicles

```text
vehicles
--------
id UUID PK
company_id UUID NULL
plate VARCHAR
brand VARCHAR NULL
model VARCHAR NULL
year SMALLINT NULL
vehicle_type VARCHAR
status VARCHAR
current_odometer_km NUMERIC(12,2) DEFAULT 0
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

---

## 19. riders

```text
riders
------
id UUID PK
user_id UUID UNIQUE FK -> users
company_id UUID NULL FK -> companies
rider_type VARCHAR
status VARCHAR
capacity_status VARCHAR
vehicle_id UUID NULL FK -> vehicles
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

`rider_type`:
- CORPORATE
- NETWORK

`status`:
- OFFLINE
- AVAILABLE
- ON_ROUTE
- PAUSED
- OUT_OF_SERVICE

`capacity_status`:
- EMPTY
- AVAILABLE_SPACE
- FULL

Implementación vigente en español:

- `repartidores`: UUID, `usuario_id` único, `empresa_id` opcional,
  `vehiculo_id` opcional, `estado_operativo`, `capacidad`, `activo` y marcas de
  tiempo;
- `historial_estado_repartidor`: motorista, estado anterior/nuevo, capacidad
  anterior/nueva, responsable, motivo y marcas de tiempo;
- el modo y alcance reemplazan la necesidad de persistir un `rider_type`
  redundante: Corporate requiere empresa y Network utiliza alcance global;
- existen índices para disponibilidad por empresa, estado y capacidad.

---

## 20. rider_shifts

```text
rider_shifts
------------
id UUID PK
rider_id UUID FK
started_at TIMESTAMPTZ
ended_at TIMESTAMPTZ NULL
start_latitude NUMERIC(9,6) NULL
start_longitude NUMERIC(9,6) NULL
operational_km NUMERIC(12,3) DEFAULT 0
services_completed INTEGER DEFAULT 0
normal_services INTEGER DEFAULT 0
priority_services INTEGER DEFAULT 0
active_minutes INTEGER DEFAULT 0
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

Implementación vigente en español:

- tabla `jornadas_repartidor` y modelo `JornadaRepartidor`;
- estados `ACTIVA` y `FINALIZADA`;
- campos de GPS de inicio y cierre con validación por pareja y rango;
- resumen persistido de kilómetros operativos, servicios, recolecciones,
  entregas, normales, prioritarios, minutos activos e incidencias;
- una restricción parcial impide dos jornadas activas para un motorista;
- una restricción exige fecha de cierre solamente para jornadas finalizadas;
- los índices permiten consultar el historial por motorista y las jornadas por
  estado y fecha;
- no se permite borrado normal de jornadas.

---

## 21. service_types

```text
service_types
-------------
id UUID PK
code VARCHAR UNIQUE
name VARCHAR
description TEXT NULL
is_active BOOLEAN
```

Ejemplos:
- BIOLOGICAL_SAMPLE
- MEDICINE
- REAGENT
- MEDICAL_SUPPLY
- DOCUMENT
- RESULT
- EQUIPMENT
- PACKAGE
- OTHER

---

## 22. service_requests

```text
service_requests
----------------
id UUID PK
request_number VARCHAR UNIQUE

company_id UUID FK
branch_id UUID NULL FK
requested_by UUID FK -> users

priority VARCHAR
service_type_id UUID NULL FK

origin_location_id UUID FK -> locations
destination_location_id UUID FK -> locations

status VARCHAR
assigned_rider_id UUID NULL FK -> riders

notes TEXT NULL

created_at TIMESTAMPTZ
assigned_at TIMESTAMPTZ NULL
pickup_arrived_at TIMESTAMPTZ NULL
picked_up_at TIMESTAMPTZ NULL
delivery_arrived_at TIMESTAMPTZ NULL
delivered_at TIMESTAMPTZ NULL
cancelled_at TIMESTAMPTZ NULL

updated_at TIMESTAMPTZ
```

`priority`:
- NORMAL
- PRIORITY

Estados sugeridos:
- PENDING
- ASSIGNED
- GOING_TO_PICKUP
- AT_PICKUP
- PICKED_UP
- IN_TRANSIT
- AT_DESTINATION
- DELIVERED
- CANCELLED
- PICKUP_FAILED
- DELIVERY_FAILED

---

## 23. request_items

```text
request_items
-------------
id UUID PK
request_id UUID FK
item_type VARCHAR
description TEXT NULL
quantity NUMERIC(12,2) DEFAULT 1
reference_code VARCHAR NULL
transport_condition VARCHAR NULL
notes TEXT NULL
created_at TIMESTAMPTZ
```

Implementación vigente en español:

- `tipos_servicio`: UUID, `codigo`, `nombre`, `descripcion`, `activo`;
- `solicitudes`: UUID, `numero`, `empresa_id`, `sucursal_id`,
  `solicitada_por_id`, `prioridad`, `modalidad`, `tipo_servicio_id`,
  `origen_id`, `destino_id` opcional, `destino_especial`, `estado`, notas y
  fechas operativas;
- `articulos_solicitud`: contenido, cantidad positiva, referencia, condición
  de transporte y notas;
- `eventos_solicitud`: historial inmutable por operación normal, con tipo,
  responsable, metadatos y fecha;
- existen restricciones para prioridades, estados y cantidades, además de
  índices por empresa/fecha, estado/fecha, solicitante/fecha y relaciones de
  artículos/eventos;
- `solicitudes.repartidor_asignado_id` es una llave foránea opcional al perfil
  operativo vigente;
- existe un índice por `repartidor_asignado_id` y `estado` para consultas
  operativas.
- una restricción exige destino registrado en solicitudes normales y destino
  descriptivo sin llave foránea en la modalidad `ESPECIAL`;
- `movimientos_envios_especiales` conserva una relación uno a uno con la
  solicitud, motorista, jornada, estado, coordenadas y fechas de apertura y
  cierre, kilómetros congelados y contadores de puntos considerados y
  descartados;
- una restricción parcial permite un solo movimiento especial `ACTIVO` por
  motorista y las restricciones de cierre exigen coordenadas finales para
  `FINALIZADO`.
- las opciones de creación y el resumen del solicitante son consultas sobre
  `sucursales`, `ubicaciones_empresa`, `solicitudes` y permisos existentes; no
  agregan tablas ni duplican catálogos persistidos.

El esquema conceptual en inglés de esta sección se conserva como referencia
original; los nombres persistidos por VitaGo siguen la convención oficial en
español.

---

## 24. request_assignments

```text
request_assignments
-------------------
id UUID PK
request_id UUID FK
rider_id UUID FK
assigned_by UUID NULL FK -> users
assignment_type VARCHAR
assigned_at TIMESTAMPTZ
accepted_at TIMESTAMPTZ NULL
ended_at TIMESTAMPTZ NULL
status VARCHAR
created_at TIMESTAMPTZ
```

`assignment_type`:
- AUTOMATIC
- MANUAL

Nunca perder el historial al reasignar.

Implementación vigente en español:

- `asignaciones_solicitud`: UUID, `solicitud_id`, `repartidor_id`,
  `asignada_por_id`, `tipo`, `estado`, fechas de asignación/aceptación/cierre,
  motivo y marcas de tiempo;
- tipos: `MANUAL`, `AUTOMATICA`;
- estados: `ACTIVA`, `FINALIZADA`, `CANCELADA`, `REASIGNADA`;
- una restricción parcial permite una sola asignación `ACTIVA` por solicitud;
- una restricción exige `finalizada_en` para toda asignación que ya no esté
  activa;
- los índices cubren historial por solicitud y asignaciones por motorista;
- al reasignar se cierra la fila anterior y se crea una nueva.

---

## 25. evidences

```text
evidences
---------
id UUID PK
request_id UUID FK
rider_id UUID FK
evidence_type VARCHAR
storage_key TEXT
file_url TEXT NULL
latitude NUMERIC(9,6)
longitude NUMERIC(9,6)
captured_at TIMESTAMPTZ
notes TEXT NULL
created_at TIMESTAMPTZ
```

Tipos:
- PICKUP_PHOTO
- DELIVERY_PHOTO
- INCIDENT_PHOTO

No permitir hard delete normal.

Implementación vigente en español:

- tabla `evidencias_solicitud`;
- modelo `EvidenciaSolicitud`;
- campos `solicitud`, `repartidor`, `tipo`, `clave_almacenamiento`,
  `url_archivo`, `tipo_contenido`, `tamano_bytes`, `latitud`, `longitud`,
  `capturada_en`, `notas`, `creado_en` y `actualizado_en`;
- tipos `FOTO_RECOLECCION`, `FOTO_ENTREGA` y `FOTO_INCIDENCIA`;
- restricciones para tipo, latitud y longitud;
- clave de almacenamiento única e índices por solicitud/tipo/fecha y por
  motorista/fecha;
- no existe operación HTTP de borrado.

---

## 26. request_events

```text
request_events
--------------
id BIGSERIAL PK
request_id UUID FK
event_type VARCHAR
performed_by UUID NULL FK -> users
rider_id UUID NULL FK -> riders
latitude NUMERIC(9,6) NULL
longitude NUMERIC(9,6) NULL
metadata JSONB NULL
created_at TIMESTAMPTZ
```

Sirve como timeline/auditoría.

Implementación vigente: `eventos_solicitud` incluye `repartidor`, `latitud` y
`longitud` opcionales, exige que ambas coordenadas sean nulas o válidas en
conjunto y registra los eventos de todo el ciclo operativo y de evidencias.

---

## 27. routes

```text
routes
------
id UUID PK
rider_id UUID FK
shift_id UUID FK
status VARCHAR
started_at TIMESTAMPTZ
completed_at TIMESTAMPTZ NULL
estimated_distance_km NUMERIC(12,3) NULL
actual_distance_km NUMERIC(12,3) DEFAULT 0
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

---

## 28. route_stops

```text
route_stops
-----------
id UUID PK
route_id UUID FK
request_id UUID FK
stop_type VARCHAR
location_id UUID FK
sequence INTEGER
status VARCHAR
arrived_at TIMESTAMPTZ NULL
completed_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

`stop_type`:
- PICKUP
- DELIVERY

---

## 29. route_versions

```text
route_versions
--------------
id UUID PK
route_id UUID FK
version_number INTEGER
encoded_polyline TEXT
estimated_distance_km NUMERIC(12,3)
estimated_duration_seconds INTEGER
reason VARCHAR
created_at TIMESTAMPTZ

UNIQUE(route_id, version_number)
```

Razones:
- INITIAL
- TRAFFIC_REROUTE
- NEW_REQUEST_ADDED
- MANUAL_REROUTE
- OTHER

---

## 30. location_pings

Tabla de alto volumen.

```text
location_pings
--------------
id BIGSERIAL PK
rider_id UUID FK
shift_id UUID NULL FK
route_id UUID NULL FK

latitude NUMERIC(9,6)
longitude NUMERIC(9,6)

accuracy NUMERIC(8,2) NULL
speed NUMERIC(8,2) NULL
heading NUMERIC(8,2) NULL

is_operational BOOLEAN

recorded_at TIMESTAMPTZ
```

Índices importantes:

```text
(rider_id, recorded_at DESC)
(route_id, recorded_at)
(shift_id, recorded_at)
```

Evaluar particionamiento por fecha si el volumen crece.

---

## 31. route_deviations

```text
route_deviations
----------------
id UUID PK
route_id UUID FK
rider_id UUID FK
started_at TIMESTAMPTZ
ended_at TIMESTAMPTZ NULL
max_distance_from_route_m NUMERIC(10,2)
warning_sent BOOLEAN DEFAULT FALSE
incident_created BOOLEAN DEFAULT FALSE
reason_code VARCHAR NULL
reason_notes TEXT NULL
review_status VARCHAR
reviewed_by UUID NULL FK -> users
reviewed_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ
```

No convertir detección automáticamente en penalización.

---

## 32. rider_status_history

```text
rider_status_history
--------------------
id BIGSERIAL PK
rider_id UUID FK
status VARCHAR
capacity_status VARCHAR
changed_by UUID NULL
created_at TIMESTAMPTZ
```

Útil para auditoría.

---

## 33. rate_plans

Usado principalmente en External.

```text
rate_plans
----------
id UUID PK
name VARCHAR
base_rate NUMERIC(12,2) DEFAULT 0
price_per_km NUMERIC(12,4)
minimum_charge NUMERIC(12,2) DEFAULT 0
priority_multiplier NUMERIC(8,4) DEFAULT 1
currency_code VARCHAR(3)
active_from TIMESTAMPTZ
active_until TIMESTAMPTZ NULL
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

Corporate no usa pricing.

---

## 34. request_pricing

```text
request_pricing
---------------
id UUID PK
request_id UUID UNIQUE FK
rate_plan_id UUID NULL FK
quoted_distance_km NUMERIC(12,3)
base_rate NUMERIC(12,2)
price_per_km NUMERIC(12,4)
priority_multiplier NUMERIC(8,4)
subtotal NUMERIC(12,2)
total NUMERIC(12,2)
currency_code VARCHAR(3)
calculated_at TIMESTAMPTZ
```

Guardar snapshot de tarifa.

No recalcular históricos cuando cambie `rate_plans`.

---

## 35. vehicle_maintenance

```text
vehicle_maintenance
-------------------
id UUID PK
vehicle_id UUID FK
maintenance_type VARCHAR
performed_at TIMESTAMPTZ
performed_at_km NUMERIC(12,2)
next_due_km NUMERIC(12,2) NULL
next_due_date DATE NULL
cost NUMERIC(12,2) NULL
notes TEXT NULL
created_at TIMESTAMPTZ
```

---

## 36. operational_settings

```text
operational_settings
--------------------
id UUID PK
key VARCHAR UNIQUE
value JSONB
description TEXT NULL
updated_at TIMESTAMPTZ
```

Ejemplos:

```text
ROUTE_WARNING_DISTANCE_M
ROUTE_WARNING_SECONDS
ROUTE_INCIDENT_DISTANCE_M
ROUTE_INCIDENT_SECONDS
GPS_PING_INTERVAL_SECONDS
MAX_ACTIVE_NORMAL_REQUESTS
```

Estos valores no deben quedar hardcodeados en el frontend.

---

## 37. Restricciones importantes

Considerar CHECK constraints:

```text
priority IN ('NORMAL', 'PRIORITY')
```

```text
capacity_status IN ('EMPTY', 'AVAILABLE_SPACE', 'FULL')
```

```text
rider status...
```

Sin embargo, si el backend usa enums centralizados y las migraciones controlan cambios, se puede optar por PostgreSQL enums o tablas catálogo.

Preferencia para sistemas que evolucionan:
- tablas catálogo o varchar + CHECK bien administrados.

---

## 38. Índices recomendados

Como mínimo:

```text
service_requests(company_id, created_at DESC)
service_requests(status, created_at DESC)
service_requests(assigned_rider_id, status)
request_events(request_id, created_at)
request_assignments(request_id, assigned_at)
evidences(request_id, evidence_type)
route_stops(route_id, sequence)
location_pings(rider_id, recorded_at DESC)
route_deviations(rider_id, started_at DESC)
company_locations(company_id, status)
```

---

## 39. Reglas de integridad que backend + DB deben respetar

1. Solicitud entregada requiere evidencia de entrega.
2. Solicitud recolectada requiere evidencia de pickup.
3. Corporate no debe guardar password corporativo.
4. Solicitud debe usar ubicaciones válidas.
5. En External, origen/destino deben estar autorizados para la empresa según reglas.
6. No borrar eventos históricos.
7. Reasignaciones deben conservar historia.
8. Precio histórico queda congelado.
9. Kilómetros facturados y reales son campos distintos.
10. GPS operativo y GPS no operativo deben poder distinguirse.

Algunas de estas reglas pueden implementarse en backend en vez de triggers, pero deben estar documentadas y testeadas.

---

## 40. Multi-país

No crear columnas llamadas específicamente:

```text
departamento
municipio
```

Usar:

```text
admin_level_1
admin_level_2
locality
```

La UI decide cómo mostrarlos por país.

---

## 41. Datos sensibles

Evitar guardar información clínica que no sea necesaria.

Preferir:

- código de muestra;
- referencia;
- tipo logístico;
- cantidad;
- condición de transporte.

No almacenar diagnósticos o historia clínica salvo que exista un requerimiento explícito posterior.

---

## 42. Backups y separación

Corporate y External deben tener:

- backups independientes;
- usuarios DB independientes;
- secrets independientes;
- storage independiente;
- logs independientes.

Nunca usar la misma `DATABASE_URL`.

---

## 43. Pendientes configurables

No fijar todavía:

- precio exacto por km;
- tarifa mínima;
- multiplicador de prioridad;
- frecuencia exacta de GPS;
- metros de tolerancia;
- segundos de tolerancia;
- máximo de servicios simultáneos;
- periodo de retención GPS;
- compresión/retención de evidencias.

Todos deben quedar parametrizables.

---

## 44. Recomendación para primera migración

Orden sugerido:

1. countries
2. companies
3. location_types
4. locations
5. branches
6. company_locations
7. users
8. roles
9. permissions
10. role_permissions
11. user_roles
12. auth_sessions
13. vehicles
14. riders
15. rider_shifts
16. service_types
17. service_requests
18. request_items
19. request_assignments
20. evidences
21. request_events
22. routes
23. route_stops
24. route_versions
25. location_pings
26. route_deviations
27. rider_status_history
28. rate_plans
29. request_pricing
30. vehicle_maintenance
31. operational_settings

---

## 45. Objetivo para Codex

Codex debe usar este documento como contrato funcional inicial.

Antes de implementar una decisión que contradiga una regla de este documento, debe:
- mantener la regla;
- o documentar claramente por qué necesita cambiarse.

No inventar flujos de negocio que no estén aquí definidos.

---

## 46. Persistencia vigente de registros GPS

La tabla `registros_ubicacion` conserva:

- `id` UUID;
- `id_cliente` UUID generado por el dispositivo;
- `repartidor_id`, `jornada_id` y `movimiento_envio_especial_id` opcional;
- latitud y longitud;
- precisión en metros;
- velocidad en metros por segundo;
- rumbo en grados;
- fecha real del dispositivo en `registrada_en`;
- clasificación booleana `es_operativo`;
- marcas de creación y actualización.

Restricciones e índices:

- unicidad de `(repartidor_id, id_cliente)` para idempotencia;
- rangos válidos de coordenadas, precisión, velocidad y rumbo;
- índice por motorista y fecha descendente;
- índice por jornada y fecha descendente;
- índice por motorista, clasificación operativa y fecha descendente.
- índice por movimiento especial y fecha para reconstruir el recorrido.

La fila no referencia directamente una solicitud normal porque un motorista
puede transportar varias a la vez. Solo durante el movimiento exclusivo de un
envío especial se enlaza al movimiento correspondiente. Su kilometraje se
congela al cerrar y los puntos tardíos no lo recalculan.

---

## 47. Persistencia vigente de incidencias operativas

La tabla `incidencias` conserva:

- `id` UUID, `jornada_id` y `repartidor_id` obligatorios;
- `solicitud_id` opcional para relacionar el problema con un servicio;
- estado `ABIERTA`, `EN_REVISION` o `CERRADA`;
- descripción, coordenadas opcionales y fecha real `reportada_en`;
- usuario y fecha de revisión, además de `cerrada_en` cuando corresponda;
- marcas de creación y actualización.

La tabla `eventos_incidencia` registra de forma auditable el alta, la revisión,
el cierre y la incorporación de evidencias, incluyendo usuario responsable,
estados anterior y nuevo, notas y metadatos.

La tabla `evidencias_incidencia` conserva la clave privada de almacenamiento,
tipo de contenido, tamaño, coordenadas, fecha de captura, notas y el motorista
que adjuntó la imagen. No se publica una URL directa al archivo.

Restricciones e índices:

- las coordenadas deben existir en pareja y respetar sus rangos;
- los datos de revisión deben ser coherentes con el estado;
- una incidencia cerrada debe conservar `cerrada_en`;
- se indexan las consultas por jornada, solicitud, motorista, estado y fecha;
- las relaciones operativas usan borrado protegido y no existe borrado normal
  mediante la API.
