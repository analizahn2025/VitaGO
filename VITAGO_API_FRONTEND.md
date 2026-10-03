# Contrato de API para el frontend de VitaGo

## 1. Propósito

Este documento registra el contrato HTTP que el frontend puede consumir del
backend de VitaGo. Debe actualizarse cuando se agregue o cambie cualquiera de
estos elementos:

- endpoint;
- método HTTP;
- autenticación o permiso;
- campo de entrada o salida;
- código HTTP;
- estado o catálogo;
- regla que afecte la experiencia del usuario.

El código del backend sigue siendo la fuente técnica definitiva. Este archivo
es la referencia de integración para el frontend y solo presenta como
**disponibles** las funciones que ya están implementadas.

Última actualización: **2026-10-02**.

## 2. Historial de cambios

| Versión | Fecha | Cambio |
|---|---|---|
| 0.22.1 | 2026-10-02 | `opciones-creacion/` informa con `mensaje_disponibilidad` cuando no hay sucursales de origen o destino, conservando respuesta `200` y listas vacías. |
| 0.22.0 | 2026-10-01 | Corporate asigna al motorista elegible más cercano según GPS al crear; se corrigió el listado de disponibles y la consulta inicial entre sucursales. |
| 0.21.0 | 2026-10-01 | Solo motocicletas nuevas; cinco solicitudes activas calculadas por motorista; notificaciones persistentes; errores de artículos con índice y campo. |
| 0.20.1 | 2026-09-30 | Se preparó un escenario ficticio local de Analiza para probar las pantallas de solicitante y motorista; no cambia el contrato HTTP. |
| 0.20.0 | 2026-09-29 | Se agregó la consulta del perfil propio del motorista, con estado, capacidad y vehículo, sin ampliar el acceso a otros perfiles. |
| 0.19.1 | 2026-09-29 | Se agregó una guía de integración para las pantallas del motorista y se aclararon las limitaciones actuales de perfil propio, rutas y kilometraje. |
| 0.19.0 | 2026-09-29 | Se agregaron opciones de creación filtradas por modalidad y el resumen de solicitudes visibles para construir las pantallas del solicitante. |
| 0.18.0 | 2026-09-29 | Se unificó la supervisión corporativa en `GERENTE_OPERACIONES`, que ahora administra usuarios y roles operativos. |
| 0.17.0 | 2026-09-28 | Se agregaron las modalidades exclusivas de Analiza, el rol gerente de operaciones y el kilometraje GPS congelado de envíos especiales. |
| 0.16.0 | 2026-09-28 | Se documentaron los JSON completos de solicitudes, vehículos, motoristas, asignaciones y transiciones, junto con los permisos operativos exactos. |
| 0.15.0 | 2026-09-26 | Se agregaron reporte, consulta, revisión auditada y evidencias privadas de incidencias operativas. |
| 0.14.0 | 2026-09-26 | Se agregaron recepción GPS por lotes, reintentos idempotentes, clasificación operativa y seguimiento contextual de solicitudes activas. |
| 0.13.0 | 2026-09-26 | Se agregaron inicio, consulta, historial y finalización de jornadas de motoristas con resumen operativo congelado. |
| 0.12.0 | 2026-09-26 | Se agregaron transiciones operativas controladas, evidencias privadas de recolección/entrega/incidencia y cierre automático de asignaciones. |
| 0.11.0 | 2026-09-25 | Ubicaciones expone `departamento`, `municipio`, `ciudad` y `colonia`; se retiraron los nombres públicos genéricos de niveles administrativos. |
| 0.10.0 | 2026-09-25 | Se agregaron vehículos, motoristas, disponibilidad operativa y asignación/reasignación manual de solicitudes con historial. |
| 0.9.0 | 2026-09-24 | Se agregó el catálogo de tipos de servicio y la creación, listado y detalle de solicitudes con visibilidad por responsabilidad. |
| 0.8.0 | 2026-09-24 | Se agregó la consulta, asignación y revocación auditada de roles de usuarios. |
| 0.7.0 | 2026-09-24 | Se agregó el detalle, actualización de perfil/estado y restablecimiento administrativo de contraseña de usuarios. |
| 0.6.0 | 2026-09-24 | Se agregaron las API administrativas para usuarios, roles asignables, ubicaciones autorizadas y creación de sucursales. |
| 0.5.0 | 2026-09-24 | Se agregó el catálogo inicial y la consulta protegida de tipos de ubicación. |
| 0.4.0 | 2026-09-24 | Se agregaron consultas paginadas de empresas y sucursales con autorización por permiso y alcance. |
| 0.3.0 | 2026-09-22 | Se separó el modo de aplicación del proveedor de autenticación; Corporate puede usar autenticación local únicamente durante el desarrollo. |
| 0.2.0 | 2026-09-22 | Se agregó la consulta protegida del perfil local, contexto organizacional, roles y permisos vigentes. |
| 0.1.2 | 2026-09-22 | Se agregó medición de rendimiento mediante `Server-Timing` sin modificar los cuerpos JSON. |
| 0.1.1 | 2026-09-21 | Inicio de sesión reducido a correo y contraseña; renovación reducida al refresh token; errores de autenticación pública normalizados a 401. |
| 0.1.0 | 2026-09-21 | Documento inicial con salud y autenticación corporativa/externa. |

## 3. Convenciones generales

### Ruta base

Todas las rutas actuales comienzan con:

```text
/api/v1/
```

El dominio depende del entorno. El frontend debe recibirlo mediante su propia
configuración y no debe fijarlo dentro del código.

Ejemplo conceptual:

```text
https://api.ejemplo.com/api/v1/
```

### Formato

- Solicitudes y respuestas: `application/json`, salvo la carga de evidencias,
  que utiliza `multipart/form-data`.
- Identificadores: UUID representados como texto.
- Fechas: ISO 8601 con zona horaria, normalmente UTC.
- Nombres controlados por VitaGo: español en `snake_case`.
- Autorización: `Authorization: Bearer <token>`.
- Una respuesta `204 No Content` no contiene JSON.
- Las respuestas de la API pueden incluir `Server-Timing` con el tiempo interno
  de procesamiento del backend expresado en milisegundos.

Ejemplo:

```http
Server-Timing: aplicacion;dur=150.11
```

Este valor es diagnóstico y no forma parte de las decisiones funcionales del
frontend.

El frontend no debe calcular la vigencia de los tokens con duraciones
hardcodeadas. Debe usar `expira_token_acceso_en` y
`expira_token_refresco_en` recibidos del backend.

## 4. Modos de despliegue

El mismo backend se ejecuta en dos modos separados.

### CORPORATIVO

- El proveedor definitivo es el sistema corporativo central mediante JWT.
- Durante el desarrollo local puede configurarse temporalmente el proveedor
  `LOCAL`, con el mismo flujo de correo y contraseña utilizado por Network.
- En producción, VitaGo Corporate rechaza el proveedor local.
- Al activar `JWT_CORPORATIVO`, el frontend obtiene el JWT del proveedor
  corporativo y VitaGo no recibe ni almacena la contraseña corporativa.

El JWT corporativo debe contener la identidad acordada con el proveedor. El
nombre predeterminado del claim es `sub`, aunque es configurable por despliegue.

### EXTERNO

- VitaGo valida correo y contraseña.
- VitaGo devuelve access token y refresh token.
- El access token se envía en los endpoints protegidos.
- El refresh token se utiliza únicamente para renovar la sesión.
- Cada renovación reemplaza tanto el access token como el refresh token.

## 5. Resumen de endpoints disponibles

| Método | Ruta | Modo | Autenticación | Respuesta correcta |
|---|---|---|---|---|
| `GET` | `/api/v1/salud/` | Ambos | Pública | `200` |
| `POST` | `/api/v1/autenticacion/iniciar-sesion/` | Proveedor `LOCAL` | Pública | `200` |
| `POST` | `/api/v1/autenticacion/renovar/` | Proveedor `LOCAL` | Refresh token en JSON | `200` |
| `POST` | `/api/v1/autenticacion/cerrar-sesion/` | Proveedor `LOCAL` | Access token | `204` |
| `POST` | `/api/v1/autenticacion/cerrar-todas-las-sesiones/` | Proveedor `LOCAL` | Access token | `204` |
| `GET` | `/api/v1/usuarios/mi-perfil/` | Ambos | Access token de VitaGo o JWT corporativo | `200` |
| `GET` | `/api/v1/usuarios/` | Ambos | Bearer + `usuario.ver` | `200` |
| `POST` | `/api/v1/usuarios/` | Ambos | Bearer + `usuario.administrar` y `rol.asignar` | `201` |
| `GET` | `/api/v1/usuarios/roles-asignables/` | Ambos | Bearer + administración de usuarios en alcance | `200` |
| `GET` | `/api/v1/usuarios/{usuario_id}/` | Ambos | Bearer + `usuario.ver` en alcance | `200` |
| `PATCH` | `/api/v1/usuarios/{usuario_id}/` | Ambos | Bearer + `usuario.administrar` en alcance | `200` |
| `POST` | `/api/v1/usuarios/{usuario_id}/restablecer-contrasena/` | Proveedor `LOCAL` | Bearer + `usuario.administrar` en alcance | `204` |
| `GET` | `/api/v1/usuarios/{usuario_id}/roles/` | Ambos | Bearer + `usuario.ver` en alcance | `200` |
| `POST` | `/api/v1/usuarios/{usuario_id}/roles/` | Ambos | Bearer + `usuario.administrar` y `rol.asignar` en alcance | `201` |
| `DELETE` | `/api/v1/usuarios/{usuario_id}/roles/{asignacion_id}/` | Ambos | Bearer + `usuario.administrar` y `rol.asignar` en alcance | `204` |
| `GET` | `/api/v1/organizaciones/empresas/` | Ambos | Bearer + `empresa.ver` | `200` |
| `GET` | `/api/v1/organizaciones/empresas/{empresa_id}/` | Ambos | Bearer + `empresa.ver` en alcance | `200` |
| `GET` | `/api/v1/organizaciones/empresas/{empresa_id}/sucursales/` | Ambos | Bearer + `sucursal.ver` en alcance | `200` |
| `POST` | `/api/v1/organizaciones/empresas/{empresa_id}/sucursales/` | Ambos | Bearer + `sucursal.administrar` en alcance | `201` |
| `GET` | `/api/v1/organizaciones/sucursales/{sucursal_id}/` | Ambos | Bearer + `sucursal.ver` en alcance | `200` |
| `GET` | `/api/v1/ubicaciones/` | Ambos | Bearer + `ubicacion.ver` en alcance | `200` |
| `POST` | `/api/v1/ubicaciones/` | Ambos | Bearer + `ubicacion.crear` en alcance | `201` |
| `GET` | `/api/v1/ubicaciones/tipos/` | Ambos | Bearer + `ubicacion.ver` | `200` |
| `GET` | `/api/v1/ubicaciones/{ubicacion_id}/` | Ambos | Bearer + `ubicacion.ver` en alcance | `200` |
| `PATCH` | `/api/v1/ubicaciones/{ubicacion_id}/autorizacion-empresa/{empresa_id}/` | Ambos | Bearer + `ubicacion.aprobar` en alcance | `200` |
| `GET` | `/api/v1/solicitudes/tipos-servicio/` | Ambos | Bearer + permiso relacionado con solicitudes | `200` |
| `GET` | `/api/v1/solicitudes/opciones-creacion/` | Corporate | Bearer + `solicitud.crear` en alcance | `200` |
| `GET` | `/api/v1/solicitudes/resumen-solicitante/` | Ambos | Bearer + visibilidad de solicitudes | `200` |
| `GET` | `/api/v1/solicitudes/` | Ambos | Bearer + visibilidad de solicitudes | `200` |
| `POST` | `/api/v1/solicitudes/` | Corporate | Bearer + `solicitud.crear`; especiales requieren además `solicitud.crear_envio_especial` con alcance de empresa | `201` |
| `GET` | `/api/v1/solicitudes/{solicitud_id}/` | Ambos | Bearer + visibilidad de la solicitud | `200` |
| `POST` | `/api/v1/solicitudes/{solicitud_id}/asignaciones/` | Ambos | Bearer + `solicitud.asignar` o `solicitud.reasignar` | `201` |
| `POST` | `/api/v1/solicitudes/{solicitud_id}/transiciones/` | Ambos | Motorista asignado + `solicitud.actualizar_estado`, o `solicitud.cancelar` para cancelar | `200` |
| `GET` | `/api/v1/solicitudes/{solicitud_id}/evidencias/` | Ambos | Bearer + visibilidad de solicitud + `evidencia.ver` | `200` |
| `POST` | `/api/v1/solicitudes/{solicitud_id}/evidencias/` | Ambos | Motorista asignado + `evidencia.crear` | `201` |
| `GET` | `/api/v1/solicitudes/{solicitud_id}/evidencias/{evidencia_id}/archivo/` | Ambos | Bearer + visibilidad de solicitud + `evidencia.ver` | `200` |
| `GET` | `/api/v1/vehiculos/` | Ambos | Bearer + `vehiculo.ver` | `200` |
| `POST` | `/api/v1/vehiculos/` | Ambos | Bearer + `vehiculo.administrar` | `201` |
| `GET` | `/api/v1/vehiculos/{vehiculo_id}/` | Ambos | Bearer + `vehiculo.ver` en alcance | `200` |
| `GET` | `/api/v1/repartidores/` | Ambos | Bearer + `repartidor.ver` | `200` |
| `POST` | `/api/v1/repartidores/` | Ambos | Bearer + `repartidor.administrar` | `201` |
| `GET` | `/api/v1/repartidores/disponibles/` | Ambos | Bearer + `repartidor.ver` | `200` |
| `GET` | `/api/v1/repartidores/mi-perfil/` | Ambos | Motorista autenticado con perfil activo | `200` |
| `GET` | `/api/v1/repartidores/{repartidor_id}/` | Ambos | Bearer + `repartidor.ver` en alcance | `200` |
| `PATCH` | `/api/v1/repartidores/{repartidor_id}/operacion/` | Ambos | Motorista propio o `repartidor.administrar` | `200` |
| `GET` | `/api/v1/notificaciones/` | Ambos | Bearer; solo las propias | `200` |
| `GET` | `/api/v1/notificaciones/conteo-no-leidas/` | Ambos | Bearer; solo las propias | `200` |
| `POST` | `/api/v1/notificaciones/{notificacion_id}/marcar-leida/` | Ambos | Bearer; solo la propia | `200` |
| `POST` | `/api/v1/jornadas/iniciar/` | Ambos | Motorista propio + `jornada.iniciar` | `201` |
| `GET` | `/api/v1/jornadas/activa/` | Ambos | Motorista propio + `jornada.ver` | `200` |
| `GET` | `/api/v1/jornadas/` | Ambos | Bearer + `jornada.ver` | `200` |
| `GET` | `/api/v1/jornadas/{jornada_id}/` | Ambos | Bearer + `jornada.ver` en alcance | `200` |
| `POST` | `/api/v1/jornadas/{jornada_id}/finalizar/` | Ambos | Motorista propietario + `jornada.finalizar` | `200` |
| `POST` | `/api/v1/seguimiento/registros/` | Ambos | Motorista propio + `repartidor.registrar_ubicacion` | `201` |
| `GET` | `/api/v1/solicitudes/{solicitud_id}/seguimiento/` | Ambos | Visibilidad de solicitud + `solicitud.ver_seguimiento` | `200` |
| `GET` | `/api/v1/incidencias/` | Ambos | Motorista propio o `incidencia.revisar` en alcance | `200` |
| `POST` | `/api/v1/incidencias/` | Ambos | Motorista propio + `incidencia.crear` | `201` |
| `GET` | `/api/v1/incidencias/{incidencia_id}/` | Ambos | Motorista propietario o `incidencia.revisar` en alcance | `200` |
| `POST` | `/api/v1/incidencias/{incidencia_id}/revision/` | Ambos | Bearer + `incidencia.revisar` en alcance | `200` |
| `GET` | `/api/v1/incidencias/{incidencia_id}/evidencias/` | Ambos | Visibilidad de incidencia | `200` |
| `POST` | `/api/v1/incidencias/{incidencia_id}/evidencias/` | Ambos | Motorista propietario + `evidencia.crear` | `201` |
| `GET` | `/api/v1/incidencias/{incidencia_id}/evidencias/{evidencia_id}/archivo/` | Ambos | Visibilidad de incidencia | `200` |

## 6. Respuestas de error

### Error general

Los errores de autenticación o disponibilidad normalmente tienen esta forma:

```json
{
  "detail": "Descripción del error."
}
```

### Error de validación

Los campos inválidos se devuelven por nombre:

```json
{
  "correo": [
    "Introduzca una dirección de correo electrónico válida."
  ],
  "contrasena": [
    "Este campo es requerido."
  ]
}
```

### Códigos actuales

| Código | Significado para el frontend |
|---|---|
| `400` | Faltan campos o el formato enviado no es válido. |
| `401` | Las credenciales o el token son inválidos, expiraron o corresponden a una sesión revocada. |
| `403` | El usuario está autenticado, pero no posee el permiso requerido en ningún alcance. |
| `404` | El endpoint no está disponible con el proveedor de autenticación actual. |
| `409` | La operación entra en conflicto con una regla vigente; actualmente se usa para impedir solicitudes Network sin cotización. |
| `500` | Error interno no esperado; no debe mostrarse el detalle técnico al usuario. |

Los mensajes sirven para informar al usuario, pero el flujo del frontend debe
decidirse principalmente por el código HTTP.

## 7. Salud del servicio

### `GET /api/v1/salud/`

Comprueba que el proceso HTTP de VitaGo responde.

Autenticación: no requerida.

Respuesta `200 OK`:

```json
{
  "estado": "correcto",
  "servicio": "VitaGo"
}
```

`servicio` identifica la instancia configurada. En el entorno local de
Corporate su valor es `VitaGo Corporate`; en Network es `VitaGo`.

Este endpoint no confirma por sí solo que PostgreSQL o servicios externos estén
disponibles.

## 8. Inicio de sesión local

### `POST /api/v1/autenticacion/iniciar-sesion/`

Disponible cuando `PROVEEDOR_AUTENTICACION=LOCAL`, tanto en Network como en el
entorno local temporal de Corporate.

Autenticación: no requerida.

Solicitud:

```json
{
  "correo": "usuario@empresa.com",
  "contrasena": "valor-secreto"
}
```

Campos:

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `correo` | texto | Sí | Correo válido, máximo 254 caracteres. |
| `contrasena` | texto | Sí | Máximo 128 caracteres. |

El backend obtiene automáticamente la dirección IP y el agente de usuario que
estén disponibles en la solicitud; el frontend no envía datos del dispositivo
en este contrato.

Respuesta `200 OK`:

```json
{
  "token_acceso": "eyJ...",
  "token_refresco": "eyJ...",
  "tipo_token": "Bearer",
  "expira_token_acceso_en": "2026-09-21T20:00:00Z",
  "expira_token_refresco_en": "2026-09-28T19:45:00Z",
  "sesion_id": "0b6be16f-4695-46ec-8d75-dbf2566e49e2",
  "usuario": {
    "id": "40bc6f06-8634-4103-93d9-aeebda6b19e0",
    "correo": "usuario@empresa.com",
    "nombres": "Nombre",
    "apellidos": "Apellido"
  }
}
```

Errores relevantes:

- `400`: campos inválidos o ausentes.
- `401`: credenciales inválidas o usuario inactivo.
- `404`: endpoint solicitado en modo `CORPORATIVO`.

El backend utiliza un mensaje genérico para no revelar si un correo está
registrado.

## 9. Renovación de sesión externa

### `POST /api/v1/autenticacion/renovar/`

Disponible únicamente cuando `PROVEEDOR_AUTENTICACION=LOCAL`.

Autenticación: el refresh token se envía en el cuerpo; no requiere access token.

Solicitud:

```json
{
  "token_refresco": "eyJ..."
}
```

Campos:

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `token_refresco` | texto | Sí | Máximo 4096 caracteres. |

Respuesta `200 OK`:

```json
{
  "token_acceso": "eyJ...",
  "token_refresco": "eyJ...",
  "tipo_token": "Bearer",
  "expira_token_acceso_en": "2026-09-21T20:15:00Z",
  "expira_token_refresco_en": "2026-09-28T20:00:00Z",
  "sesion_id": "91991cc7-5764-47cf-946c-7f464665d7b8"
}
```

Reglas para el frontend:

1. Reemplazar de forma conjunta los dos tokens anteriores.
2. No intentar reutilizar el refresh token anterior.
3. Evitar renovaciones paralelas de la misma sesión.
4. Si la renovación falla, eliminar las credenciales locales y solicitar un
   nuevo inicio de sesión.

Errores relevantes:

- `400`: entrada inválida.
- `401`: token inválido, expirado, revocado o reutilizado.
- `404`: endpoint solicitado en modo `CORPORATIVO`.

La reutilización de un refresh token revocado puede invalidar la familia de
sesiones activa como medida de seguridad.

## 10. Cierre de la sesión actual

### `POST /api/v1/autenticacion/cerrar-sesion/`

Disponible únicamente cuando `PROVEEDOR_AUTENTICACION=LOCAL`.

Encabezado obligatorio:

```http
Authorization: Bearer <token_acceso>
```

Cuerpo: no requerido.

Respuesta correcta:

```text
204 No Content
```

Después de recibir `204`, el frontend debe eliminar localmente el access token,
el refresh token y los datos privados asociados a la sesión.

Errores relevantes:

- `401`: access token ausente, inválido o sesión no vigente.
- `404`: endpoint no disponible con el proveedor de autenticación actual.

## 11. Cierre de todas las sesiones

### `POST /api/v1/autenticacion/cerrar-todas-las-sesiones/`

Disponible únicamente cuando `PROVEEDOR_AUTENTICACION=LOCAL`.

Encabezado obligatorio:

```http
Authorization: Bearer <token_acceso>
```

Cuerpo: no requerido.

Respuesta correcta:

```text
204 No Content
```

Revoca todas las sesiones activas del usuario, incluida la sesión que realiza la
solicitud. El frontend debe eliminar todas las credenciales locales al recibir
la respuesta.

Errores relevantes:

- `401`: access token ausente, inválido o sesión no vigente.
- `404`: endpoint no disponible con el proveedor de autenticación actual.

## 12. Perfil del usuario autenticado

### `GET /api/v1/usuarios/mi-perfil/`

Disponible en los modos `CORPORATIVO` y `EXTERNO`.

Encabezado obligatorio:

```http
Authorization: Bearer <token_acceso>
```

Con el proveedor `LOCAL` se utiliza el access token emitido por VitaGo. Con el
proveedor `JWT_CORPORATIVO` se utiliza el JWT emitido por el sistema central.

Cuerpo: no requerido.

Respuesta `200 OK`:

```json
{
  "usuario": {
    "id": "40bc6f06-8634-4103-93d9-aeebda6b19e0",
    "correo": "usuario@empresa.com",
    "nombres": "Nombre",
    "apellidos": "Apellido",
    "telefono": "+50499999999",
    "estado": "ACTIVO"
  },
  "empresa": {
    "id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
    "nombre": "Empresa de ejemplo"
  },
  "sucursal": null,
  "roles": [
    {
      "codigo": "SOLICITANTE_EXTERNO",
      "nombre": "Solicitante externo",
      "tipo_alcance": "EMPRESA",
      "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "sucursal_id": null
    }
  ],
  "permisos": [
    "solicitud.crear",
    "solicitud.ver"
  ]
}
```

Reglas del contrato:

- `empresa` y `sucursal` pueden ser `null`.
- `telefono` puede ser `null` o texto vacío.
- `roles` contiene solamente asignaciones activas cuyos roles están activos.
- `tipo_alcance` puede ser `GLOBAL`, `EMPRESA` o `SUCURSAL`.
- `empresa_id` y `sucursal_id` identifican el alcance concreto del rol y
  pueden ser `null` según `tipo_alcance`.
- `permisos` contiene la unión ordenada, sin duplicados, de los permisos
  activos otorgados por los roles vigentes.
- Un superusuario recibe el catálogo completo de permisos activos.
- Un usuario sin roles recibe `roles: []` y `permisos: []`.

Los permisos recibidos sirven para construir la interfaz, pero no autorizan por
sí mismos ninguna operación. El backend vuelve a comprobar el permiso y su
alcance al atender cada endpoint protegido.

Errores relevantes:

- `401`: token ausente, inválido, expirado, revocado o perteneciente a un
  usuario inactivo.

Este endpoint es aditivo y no modifica la respuesta del inicio de sesión.

## 13. Uso del JWT corporativo

VitaGo no expone un endpoint local para iniciar sesión corporativa. El frontend
debe obtener el JWT del sistema central y enviarlo en cada endpoint protegido:

```http
Authorization: Bearer <jwt_corporativo>
```

El backend valida:

- firma RSA;
- expiración;
- issuer;
- audience;
- identificador corporativo;
- existencia y estado del usuario local.

Una respuesta `401` indica que el frontend debe solicitar al proveedor
corporativo un token válido o cerrar la sesión local. Nunca debe pedir ni enviar
la contraseña corporativa a VitaGo.

## 14. Almacenamiento y manejo de tokens

El frontend debe:

- utilizar almacenamiento seguro proporcionado por el sistema operativo;
- evitar guardar tokens en registros, analítica o mensajes de error;
- enviar el access token solamente a la API configurada de VitaGo;
- reemplazar inmediatamente el par completo después de renovar;
- limpiar tokens y datos privados al cerrar sesión;
- tratar `401` como sesión no autorizada;
- impedir que múltiples solicitudes intenten renovar simultáneamente.

El frontend no debe interpretar los claims del JWT como autorización definitiva.
Los permisos siempre los decide el backend.

## 15. Consulta de organizaciones

Todos los endpoints de esta sección requieren:

```http
Authorization: Bearer <token>
```

Las listas aceptan:

| Parámetro | Tipo | Predeterminado | Límite |
|---|---|---:|---:|
| `pagina` | entero | `1` | — |
| `tamano_pagina` | entero | `20` | `100` |

Respuesta paginada:

```json
{
  "conteo": 1,
  "pagina_siguiente": null,
  "pagina_anterior": null,
  "resultados": []
}
```

### `GET /api/v1/organizaciones/empresas/`

Devuelve únicamente las empresas visibles mediante un rol activo con el
permiso `empresa.ver`.

Respuesta `200 OK`:

```json
{
  "conteo": 1,
  "pagina_siguiente": null,
  "pagina_anterior": null,
  "resultados": [
    {
      "id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "nombre": "Analiza",
      "razon_social": null,
      "identificacion_fiscal": null,
      "telefono": null,
      "correo": null,
      "pais": {
        "id": "551f8cff-af35-480f-a803-25129d6aab03",
        "iso2": "HN",
        "nombre": "Honduras",
        "codigo_moneda": "HNL",
        "zona_horaria_predeterminada": "America/Tegucigalpa"
      },
      "estado": "ACTIVO"
    }
  ]
}
```

### `GET /api/v1/organizaciones/empresas/{empresa_id}/`

Devuelve el mismo objeto de empresa sin envoltorio de paginación. Si la empresa
existe pero está fuera del alcance del usuario, responde `404`.

### `GET /api/v1/organizaciones/empresas/{empresa_id}/sucursales/`

Devuelve las sucursales permitidas dentro de la empresa indicada. Requiere
`sucursal.ver`.

Ejemplo de elemento en `resultados`:

```json
{
  "id": "65fd8794-21a3-4a68-bc70-495355947494",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "nombre": "Principal",
  "codigo": "SPS-01",
  "telefono": null,
  "correo": null,
  "estado": "ACTIVO",
  "ubicacion": {
    "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
    "nombre": "Sede principal",
    "tipo_ubicacion": {
      "id": "14f574d2-2e84-41d2-a02e-5c233f6d7685",
      "codigo": "SUCURSAL",
      "nombre": "Sucursal"
    },
    "direccion": "Dirección registrada",
    "latitud": "14.072300",
    "longitud": "-87.192100",
    "estado": "ACTIVO"
  }
}
```

### `GET /api/v1/organizaciones/sucursales/{sucursal_id}/`

Devuelve un único objeto de sucursal con la misma estructura anterior. Una
sucursal fuera del alcance responde `404`.

Reglas de autorización:

- alcance `GLOBAL`: permite todas las organizaciones correspondientes;
- alcance `EMPRESA`: permite esa empresa y todas sus sucursales;
- alcance `SUCURSAL`: permite la empresa como contexto, pero solamente las
  sucursales asignadas;
- sin el permiso requerido: `403`;
- identificador inexistente o fuera del alcance: `404`.

Las empresas continúan siendo de consulta. La creación de sucursales está
disponible para administradores y se documenta en la sección 18; todavía no se
permite editar empresas o sucursales existentes.

## 16. Tipos de ubicación

### `GET /api/v1/ubicaciones/tipos/`

Devuelve el catálogo activo de tipos de ubicación. Requiere token Bearer y el
permiso `ubicacion.ver` en al menos un alcance vigente.

Respuesta `200 OK`:

```json
{
  "resultados": [
    {
      "id": "5f5763a1-9b81-4aec-ae87-a992f3f14039",
      "codigo": "HOSPITAL",
      "nombre": "Hospital"
    }
  ]
}
```

Catálogo inicial:

| Código | Nombre |
|---|---|
| `HOSPITAL` | Hospital |
| `CLINICA` | Clínica |
| `LABORATORIO_CLINICO` | Laboratorio clínico |
| `CONSULTORIO` | Consultorio |
| `FARMACIA` | Farmacia |
| `BANCO_SANGRE` | Banco de sangre |
| `CENTRO_IMAGENES` | Centro de imágenes |
| `CENTRO_MEDICO` | Centro médico |
| `SUCURSAL` | Sucursal |
| `RESIDENCIA` | Residencia |
| `EMPRESA` | Empresa |
| `EMPRESA_TRANSPORTE` | Empresa de transporte |
| `OTRO` | Otro |

El catálogo no utiliza paginación. Solo devuelve registros activos y se ordena
por nombre. Una respuesta `403` indica que el usuario no posee
`ubicacion.ver`.

## 17. Administración de usuarios

No existe registro público. Estas rutas están destinadas al panel
administrativo y siempre vuelven a validar permisos y alcance en el backend.

### `GET /api/v1/usuarios/`

Devuelve una lista paginada. Requiere `usuario.ver`. Un alcance de empresa ve
los usuarios de esa empresa; un alcance de sucursal ve únicamente esa sucursal;
un alcance global puede ver todos.

Cada elemento incluye:

```json
{
  "id": "40bc6f06-8634-4103-93d9-aeebda6b19e0",
  "correo": "usuario@empresa.com",
  "nombres": "Nombre",
  "apellidos": "Apellido",
  "telefono": null,
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": null,
  "estado": "ACTIVO",
  "roles": [
    {
      "codigo": "SOLICITANTE_EXTERNO",
      "nombre": "Solicitante externo",
      "tipo_alcance": "EMPRESA",
      "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "sucursal_id": null
    }
  ],
  "creado_en": "2026-09-24T16:00:00Z"
}
```

### `GET /api/v1/usuarios/roles-asignables/`

Parámetros obligatorios según el alcance que se desea asignar:

| Campo | Regla |
|---|---|
| `tipo_alcance` | `GLOBAL`, `EMPRESA` o `SUCURSAL`. |
| `empresa_id` | Obligatorio para `EMPRESA` y `SUCURSAL`. |
| `sucursal_id` | Obligatorio solamente para `SUCURSAL`. |

Devuelve únicamente roles compatibles con Corporate o Network incluidos en la
matriz de delegación del administrador. Un administrador corporativo puede
crear administradores, gerentes de operaciones, solicitantes y repartidores
corporativos, pero no superadministradores. Un gerente de operaciones puede
crear usuarios y asignar solamente `SOLICITANTE_CORPORATIVO` o
`REPARTIDOR_CORPORATIVO` dentro de su empresa. No puede crear administradores
ni otros gerentes, ni modificar, suspender o restablecer las credenciales de
administradores u otros gerentes. Un administrador de empresa externa puede crear
administradores o solicitantes de su propia empresa.

### `POST /api/v1/usuarios/`

Con el proveedor `LOCAL`:

```json
{
  "correo": "usuario@empresa.com",
  "nombres": "Nombre",
  "apellidos": "Apellido",
  "telefono": "+50499999999",
  "contrasena_temporal": "valor-secreto",
  "rol_codigo": "SOLICITANTE_EXTERNO",
  "tipo_alcance": "EMPRESA",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96"
}
```

Con `JWT_CORPORATIVO`, no se admite `contrasena_temporal` y se exige
`identificador_autenticacion_externa`. La contraseña nunca se devuelve. El
usuario y su primer rol se crean en una sola transacción.

Errores relevantes:

- `400`: datos inválidos, correo duplicado o contraseña débil;
- `403`: faltan permisos, el alcance no está permitido o el rol produciría una
  escalación de privilegios;
- `404`: empresa o sucursal inexistente, inactiva o fuera del alcance.

### `GET /api/v1/usuarios/{usuario_id}/`

Devuelve el mismo objeto documentado en el listado. Requiere `usuario.ver` en
un alcance que incluya al usuario solicitado. Un usuario existente fuera del
alcance responde `404` para no revelar información.

### `PATCH /api/v1/usuarios/{usuario_id}/`

Permite actualizar uno o más de estos campos:

```json
{
  "nombres": "Nombre actualizado",
  "apellidos": "Apellido actualizado",
  "telefono": "+50499999999",
  "estado": "SUSPENDIDO"
}
```

Los estados admitidos son `ACTIVO`, `INACTIVO` y `SUSPENDIDO`. El correo, la
empresa, la sucursal y los roles no se modifican mediante esta ruta. Cambiar un
usuario a `INACTIVO` o `SUSPENDIDO` revoca inmediatamente todas sus sesiones
activas. Un administrador no puede inactivar ni suspender su propia cuenta.

Respuesta correcta: `200 OK` con el objeto actualizado.

Errores relevantes:

- `400`: no se envió ningún campo, un valor es inválido o el administrador
  intentó inactivar/suspender su propia cuenta;
- `403`: falta `usuario.administrar`;
- `404`: el usuario no existe o está fuera del alcance permitido.

No existe eliminación física de usuarios; deben conservarse y cambiarse de
estado para mantener la trazabilidad.

### `POST /api/v1/usuarios/{usuario_id}/restablecer-contrasena/`

Disponible únicamente cuando el proveedor configurado es `LOCAL`.

```json
{
  "contrasena_temporal": "Nueva-Clave-Temporal-2026!"
}
```

La contraseña se valida con las políticas de Django, se almacena mediante el
hasher configurado y nunca se devuelve. El cambio revoca todas las sesiones
activas del usuario, por lo que deberá iniciar sesión de nuevo.

Respuesta correcta: `204 No Content`.

Errores relevantes:

- `400`: la contraseña no cumple la política configurada;
- `403`: falta `usuario.administrar` en el alcance del usuario;
- `404`: usuario inexistente/fuera de alcance o proveedor
  `JWT_CORPORATIVO`, donde la contraseña pertenece al sistema central.

### `GET /api/v1/usuarios/{usuario_id}/roles/`

Devuelve el historial de asignaciones de rol que el administrador puede ver
según `usuario.ver` y su alcance. Incluye asignaciones activas y revocadas:

```json
{
  "resultados": [
    {
      "id": "bed1b535-6775-4e42-aec7-e3b4273f6424",
      "rol": {
        "codigo": "SOLICITANTE_EXTERNO",
        "nombre": "Solicitante externo",
        "descripcion": "Solicitudes de una empresa externa.",
        "permite_alcance_global": false,
        "permite_alcance_empresa": true,
        "permite_alcance_sucursal": true
      },
      "tipo_alcance": "EMPRESA",
      "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "sucursal_id": null,
      "activo": true,
      "asignado_por_id": "756ecf12-b8ae-42ce-af5e-3e88518c2896",
      "asignado_en": "2026-09-24T18:00:00Z",
      "revocado_por_id": null,
      "revocado_en": null
    }
  ]
}
```

La lista no se pagina porque el historial de roles por usuario debe ser
pequeño. Las asignaciones activas aparecen primero.

### `POST /api/v1/usuarios/{usuario_id}/roles/`

Solicitud:

```json
{
  "rol_codigo": "SOLICITANTE_EXTERNO",
  "tipo_alcance": "EMPRESA",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": null
}
```

`empresa_id` es obligatorio para los alcances `EMPRESA` y `SUCURSAL`;
`sucursal_id` es obligatorio únicamente para `SUCURSAL`. El rol debe obtenerse
previamente desde `roles-asignables` para el mismo alcance. La respuesta
`201 Created` contiene la asignación creada con el formato anterior.

El backend impide:

- asignaciones activas duplicadas;
- roles incompatibles con Corporate o Network;
- roles fuera de la matriz de delegación del administrador;
- alcances de otra empresa o sucursal del usuario;
- escalación de privilegios.

Una asignación revocada no se reactiva ni se sobrescribe: si se concede de
nuevo, se crea otra asignación para conservar el historial.

### `DELETE /api/v1/usuarios/{usuario_id}/roles/{asignacion_id}/`

Revoca la asignación sin eliminarla físicamente. Registra el administrador y
la fecha de revocación, y cierra todas las sesiones locales activas del usuario
para que los cambios de autorización tengan efecto inmediato.

Respuesta correcta: `204 No Content`.

Protecciones:

- un administrador no puede quitarse su último rol administrativo en el
  alcance;
- no se puede dejar un alcance sin al menos otro administrador vigente;
- solamente se puede revocar un rol que el administrador también podría
  asignar;
- una asignación ya revocada responde como no encontrada.

Errores relevantes para asignar o revocar:

- `400`: asignación duplicada o protección del último administrador;
- `403`: faltan permisos, el rol no es delegable o produciría escalación;
- `404`: usuario/asignación inexistente, revocada o fuera del alcance.

## 18. Administración de ubicaciones y sucursales

### `GET /api/v1/ubicaciones/?empresa_id={empresa_id}`

`empresa_id` es obligatorio. Devuelve las relaciones de ubicaciones visibles
para la empresa indicada con paginación estándar:

```json
{
  "id": "9843ca95-dc25-4a36-a55c-764b04e900f7",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "permite_origen": true,
  "permite_destino": true,
  "estado": "APROBADO",
  "ubicacion": {
    "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
    "nombre": "Clínica Central",
    "origen": "REGISTRADA_USUARIO",
    "direccion": "Dirección registrada",
    "latitud": "14.072300",
    "longitud": "-87.192100",
    "verificada": false,
    "estado": "ACTIVO"
  }
}
```

El objeto `ubicacion` también incluye tipo, país, departamento, municipio,
ciudad, colonia, contacto, horario, instrucciones y marcas de tiempo.

### `POST /api/v1/ubicaciones/`

Ejemplo de registro manual:

```json
{
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "nombre": "Clínica Central",
  "tipo_ubicacion_id": "14f574d2-2e84-41d2-a02e-5c233f6d7685",
  "origen": "REGISTRADA_USUARIO",
  "pais_id": "551f8cff-af35-480f-a803-25129d6aab03",
  "departamento": "Francisco Morazán",
  "municipio": "Distrito Central",
  "ciudad": "Tegucigalpa",
  "colonia": "Colonia Palmira",
  "direccion": "Avenida República de Panamá, edificio 123",
  "latitud": "14.072300",
  "longitud": "-87.192100",
  "telefono": null,
  "nombre_contacto": null,
  "horario_atencion": null,
  "instrucciones": "Entregar en recepción",
  "permite_origen": true,
  "permite_destino": true
}
```

`departamento`, `municipio`, `ciudad` y `colonia` son opcionales porque no
todas las direcciones manuales o respuestas de Google contienen los cuatro
niveles. `direccion`, `latitud` y `longitud` continúan siendo obligatorios.

La API ya no expone `nivel_administrativo_1`, `nivel_administrativo_2` ni
`localidad`. El frontend debe utilizar los nombres de negocio anteriores.

Para `origen: "GOOGLE"` se exige `identificador_lugar_google`. Para
`REGISTRADA_USUARIO` ese campo no debe enviarse. La ubicación queda aprobada
automáticamente solamente si el creador también posee `ubicacion.aprobar`; de
lo contrario queda `PENDIENTE`.

### `GET /api/v1/ubicaciones/{ubicacion_id}/`

Devuelve el detalle si la ubicación pertenece a una empresa visible. Los
recursos fuera del alcance responden `404`.

### `PATCH /api/v1/ubicaciones/{ubicacion_id}/autorizacion-empresa/{empresa_id}/`

Acepta uno o más campos:

```json
{
  "permite_origen": true,
  "permite_destino": false,
  "estado": "APROBADO"
}
```

Una relación `APROBADO` debe permitir origen, destino o ambos.

### `POST /api/v1/organizaciones/empresas/{empresa_id}/sucursales/`

```json
{
  "nombre": "Principal",
  "codigo": "TGU-01",
  "ubicacion_id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
  "telefono": null,
  "correo": "principal@empresa.com"
}
```

La ubicación debe estar activa y `APROBADO` para la misma empresa. El código
se normaliza a mayúsculas y no puede repetirse dentro de la empresa.

La API ya acepta Google Place ID, pero todavía no realiza búsquedas ni llamadas
a Google Maps. Esa integración se activará cuando exista una clave restringida
por entorno.

## 19. Solicitudes

### Permisos de visibilidad

El perfil puede devolver tres permisos diferentes:

- `solicitud.ver`: consulta todas las solicitudes dentro del alcance permitido;
- `solicitud.ver_propias`: consulta únicamente las solicitudes creadas por el
  usuario dentro de su alcance;
- `solicitud.ver_asignadas`: consulta las solicitudes asignadas al perfil del
  motorista autenticado.

Los solicitantes ya no reciben `solicitud.ver`; reciben
`solicitud.ver_propias`. Los repartidores reciben
`solicitud.ver_asignadas`. El frontend debe construir la navegación usando
estos permisos nuevos.

### `GET /api/v1/solicitudes/tipos-servicio/`

Devuelve nueve tipos activos sin paginación:

```json
{
  "resultados": [
    {
      "id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
      "codigo": "MUESTRA_BIOLOGICA",
      "nombre": "Muestra biológica",
      "descripcion": "Traslado controlado de muestras biológicas."
    }
  ]
}
```

Códigos iniciales: `MUESTRA_BIOLOGICA`, `MEDICAMENTO`, `REACTIVO`,
`INSUMO_MEDICO`, `DOCUMENTO`, `RESULTADO`, `EQUIPO`, `PAQUETE` y `OTRO`.

### `GET /api/v1/solicitudes/opciones-creacion/`

Devuelve solamente las modalidades, orígenes y destinos que el usuario puede
utilizar al crear una solicitud corporativa. `empresa_id` es obligatorio.
`sucursal_id` es opcional y limita el origen. Al elegir
`ENTRE_SUCURSALES` sin origen, responde `200` con las sucursales de origen y
`destinos: []`; el frontend consulta de nuevo tras elegir el origen.
`origen_id` normalmente debe ser `origenes[].ubicacion.id`. Por compatibilidad
también se acepta `origenes[].sucursal_id` en ese parámetro, o enviar solo
`sucursal_id` para fijar el origen y obtener los destinos de la misma ciudad.

Ejemplo:

```http
GET /api/v1/solicitudes/opciones-creacion/?empresa_id=3b0407a3-bc31-4d31-9619-7a3f01ac0b96&modalidad=ENTRE_SUCURSALES&origen_id=2de2d88f-65b5-4e3e-951f-0f6faf8002e3
```

Respuesta `200`:

```json
{
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": null,
  "modalidad_seleccionada": "ENTRE_SUCURSALES",
  "mensaje_disponibilidad": null,
  "puede_crear_envio_especial": false,
  "modalidades": [
    {
      "codigo": "ENTRE_SUCURSALES",
      "nombre": "Entre sucursales",
      "requiere_destino_registrado": true,
      "presentacion_ruta": "MAPA"
    },
    {
      "codigo": "EMPRESA_TRANSPORTE",
      "nombre": "Empresa de transporte",
      "requiere_destino_registrado": true,
      "presentacion_ruta": "MAPA"
    }
  ],
  "origenes": [
    {
      "sucursal_id": "d2c7775a-8223-4cf7-b23b-e11caf453120",
      "sucursal_nombre": "Sucursal Centro",
      "ubicacion": {
        "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
        "nombre": "Sucursal Centro",
        "tipo_codigo": "SUCURSAL",
        "departamento": "Francisco Morazán",
        "municipio": "Distrito Central",
        "ciudad": "Tegucigalpa",
        "colonia": "Centro",
        "direccion": "Avenida principal",
        "latitud": "14.101200",
        "longitud": "-87.193100"
      }
    }
  ],
  "destinos": [
    {
      "sucursal_id": "bb54ddfa-a0bc-44d7-8845-6078db1ca201",
      "sucursal_nombre": "Sucursal Norte",
      "ubicacion": {
        "id": "3c18fa32-7bc2-4743-9744-f22453730413",
        "nombre": "Sucursal Norte",
        "tipo_codigo": "SUCURSAL",
        "departamento": "Francisco Morazán",
        "municipio": "Distrito Central",
        "ciudad": "Tegucigalpa",
        "colonia": "El Hato",
        "direccion": "Bulevar del Norte",
        "latitud": "14.120000",
        "longitud": "-87.180000"
      }
    }
  ]
}
```

Reglas para el frontend:

- si no se envía `modalidad`, `destinos` se devuelve como `[]`;
- con `modalidad=ENTRE_SUCURSALES` pero sin origen seleccionado, se devuelven
  los `origenes` autorizados y `destinos: []`, sin error;
- `mensaje_disponibilidad` es `null` cuando hay opciones o aún falta elegir
  un origen. Si `origenes` está vacío en `ENTRE_SUCURSALES`, responde `200`
  con `mensaje_disponibilidad: "No hay sucursales disponibles para crear
  solicitudes."`. Si ya se eligió un origen válido pero `destinos` está vacío,
  responde `200` con `mensaje_disponibilidad: "No hay sucursales de destino
  disponibles en la misma ciudad."`. Mostrar este mensaje como estado vacío,
  no como error de conexión;
- `ESPECIAL` solo aparece para `GERENTE_OPERACIONES` y devuelve destinos
  vacíos porque utiliza `destino_especial`;
- para `EMPRESA_TRANSPORTE`, `sucursal_id` y `sucursal_nombre` de cada destino
  son `null`;
- una empresa, sucursal u origen fuera del alcance responde `404`;
- solicitar `ESPECIAL` sin permiso responde `403`;
- Network responde `409` mientras la creación dependa de ruta y cotización.

### `GET /api/v1/solicitudes/resumen-solicitante/`

Acepta opcionalmente `empresa_id` y `sucursal_id`. Los conteos se calculan
exclusivamente sobre las solicitudes visibles: un solicitante cuenta solo las
propias, un motorista solo las asignadas y un gerente las de su alcance.

Respuesta `200`:

```json
{
  "total": 12,
  "pendientes": 3,
  "activas": 4,
  "entregadas": 3,
  "fallidas": 1,
  "canceladas": 1,
  "recientes": []
}
```

`recientes` contiene como máximo cinco objetos con el mismo contrato completo
del resumen de `GET /api/v1/solicitudes/`, ordenados del más nuevo al más
antiguo. Las categorías son:

- `pendientes`: `PENDING` y `ASSIGNED`;
- `activas`: desde `GOING_TO_PICKUP` hasta `AT_DESTINATION`;
- `entregadas`: `DELIVERED`;
- `fallidas`: `PICKUP_FAILED` y `DELIVERY_FAILED`;
- `canceladas`: `CANCELLED`.

### `GET /api/v1/solicitudes/`

Lista paginada y limitada por los permisos anteriores. Filtros opcionales:

| Parámetro | Valores |
|---|---|
| `empresa_id` | UUID de empresa. |
| `sucursal_id` | UUID de sucursal. |
| `prioridad` | `NORMAL` o `PRIORITY`. |
| `estado` | Uno de los estados oficiales de solicitud. |
| `modalidad` | `ENTRE_SUCURSALES`, `EMPRESA_TRANSPORTE` o `ESPECIAL` en Corporate. |

Respuesta `200` completa de ejemplo:

```json
{
  "conteo": 1,
  "pagina_siguiente": null,
  "pagina_anterior": null,
  "resultados": [
    {
      "id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
      "numero": "SOL-20260928-BF9490A0",
      "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "sucursal_id": "d2c7775a-8223-4cf7-b23b-e11caf453120",
      "solicitada_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
      "repartidor_asignado_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "prioridad": "PRIORITY",
      "modalidad": "ENTRE_SUCURSALES",
      "tipo_servicio": {
        "id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
        "codigo": "MUESTRA_BIOLOGICA",
        "nombre": "Muestra biológica",
        "descripcion": "Traslado controlado de muestras biológicas."
      },
      "origen": {
        "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
        "nombre": "Laboratorio Central",
        "direccion": "Colonia Palmira, Tegucigalpa",
        "latitud": "14.101200",
        "longitud": "-87.193100"
      },
      "destino": {
        "id": "3c18fa32-7bc2-4743-9744-f22453730413",
        "nombre": "Hospital Principal",
        "direccion": "Bulevar Suyapa, Tegucigalpa",
        "latitud": "14.085600",
        "longitud": "-87.165400"
      },
      "destino_especial": null,
      "presentacion_ruta": "MAPA",
      "kilometros_envio_especial": null,
      "estado": "AT_PICKUP",
      "creado_en": "2026-09-28T14:00:00Z"
    }
  ]
}
```

El listado no incluye `notas`, `articulos`, `eventos`, `asignaciones` ni las
fechas operativas. Para esos campos debe consultarse el detalle. Cuando la
solicitud aún no posee motorista, `repartidor_asignado_id` es `null`; cuando no
pertenece a una sucursal concreta, `sucursal_id` es `null`.

### `POST /api/v1/solicitudes/`

Disponible actualmente en Corporate. Ejemplo:

```json
{
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": null,
  "prioridad": "PRIORITY",
  "modalidad": "ENTRE_SUCURSALES",
  "tipo_servicio_id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
  "origen_id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
  "destino_id": "3c18fa32-7bc2-4743-9744-f22453730413",
  "notas": "Entregar directamente en recepción.",
  "articulos": [
    {
      "tipo_articulo": "Muestra de laboratorio",
      "descripcion": "Contenedor sellado",
      "cantidad": "2.00",
      "codigo_referencia": "LAB-2026-001",
      "condicion_transporte": "Temperatura controlada",
      "notas": null
    }
  ]
}
```

Modalidades de Corporate/Analiza:

| Código | Origen y destino | Presentación |
|---|---|---|
| `ENTRE_SUCURSALES` | Sucursal activa hacia otra sucursal activa de la misma empresa y ciudad. | `MAPA` |
| `EMPRESA_TRANSPORTE` | Sucursal activa hacia una ubicación aprobada cuyo tipo sea `EMPRESA_TRANSPORTE`. | `MAPA` |
| `ESPECIAL` | Sucursal activa hacia una descripción libre; no utiliza `destino_id`. | `SOLO_KILOMETROS` |

`ABIERTO` queda reservado para VitaGo Network y Corporate lo rechaza. Estas
reglas no restringen el modelo futuro de Network.

Ejemplo de creación especial:

```json
{
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": "d2c7775a-8223-4cf7-b23b-e11caf453120",
  "prioridad": "NORMAL",
  "modalidad": "ESPECIAL",
  "tipo_servicio_id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
  "origen_id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
  "destino_id": null,
  "destino_especial": "Entregar documentos en oficinas centrales del proveedor",
  "notas": null,
  "articulos": [
    {
      "tipo_articulo": "Documentos",
      "cantidad": "1.00"
    }
  ]
}
```

Reglas:

- requiere al menos un artículo y cada cantidad debe ser mayor que cero;
- la empresa y sucursal deben estar activas y dentro de
  `solicitud.crear`;
- el origen debe estar activo, aprobado y habilitado como origen para la
  empresa; en Corporate también debe corresponder a una sucursal activa;
- el destino debe estar activo, aprobado y habilitado como destino para la
  misma empresa;
- el tipo de servicio debe estar activo;
- el backend genera el número y crea la solicitud inicialmente `PENDING`;
  si encuentra un motorista elegible, la asigna en la misma operación y la
  respuesta `201` ya trae `estado: "ASSIGNED"` y `repartidor_asignado_id`;
- solicitud, artículos, eventos, asignación y notificación se guardan
  atómicamente;
- `ESPECIAL` exige los permisos `solicitud.crear` y
  `solicitud.crear_envio_especial`; el segundo se entrega al rol
  `GERENTE_OPERACIONES` exclusivamente con alcance `EMPRESA`;
- un supervisor o gerente de sucursal no puede crear un envío especial;
  el superusuario técnico de Django conserva su excepción administrativa.

Prioridades vigentes: `NORMAL` y `PRIORITY`.

Network responde `409 Conflict` mientras no exista cálculo de ruta y tarifa en
el backend. El frontend no debe intentar enviar precios o distancias para
evitar esta protección.

### `GET /api/v1/solicitudes/{solicitud_id}/`

Devuelve el resumen más notas, artículos, eventos y fechas operativas. Una
solicitud inexistente o fuera del alcance responde `404`.

Respuesta `200` completa de ejemplo:

```json
{
  "id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "numero": "SOL-20260928-BF9490A0",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": "d2c7775a-8223-4cf7-b23b-e11caf453120",
  "solicitada_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
  "repartidor_asignado_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "prioridad": "PRIORITY",
  "modalidad": "ENTRE_SUCURSALES",
  "tipo_servicio": {
    "id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
    "codigo": "MUESTRA_BIOLOGICA",
    "nombre": "Muestra biológica",
    "descripcion": "Traslado controlado de muestras biológicas."
  },
  "origen": {
    "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
    "nombre": "Laboratorio Central",
    "direccion": "Colonia Palmira, Tegucigalpa",
    "latitud": "14.101200",
    "longitud": "-87.193100"
  },
  "destino": {
    "id": "3c18fa32-7bc2-4743-9744-f22453730413",
    "nombre": "Hospital Principal",
    "direccion": "Bulevar Suyapa, Tegucigalpa",
    "latitud": "14.085600",
    "longitud": "-87.165400"
  },
  "destino_especial": null,
  "presentacion_ruta": "MAPA",
  "kilometros_envio_especial": null,
  "estado": "AT_PICKUP",
  "creado_en": "2026-09-28T14:00:00Z",
  "notas": "Entregar directamente en recepción.",
  "articulos": [
    {
      "id": "9067300c-8cb8-44e6-9fe5-145fcb5adef1",
      "tipo_articulo": "Muestra de laboratorio",
      "descripcion": "Contenedor sellado",
      "cantidad": "2.00",
      "codigo_referencia": "LAB-2026-001",
      "condicion_transporte": "Temperatura controlada",
      "notas": null
    }
  ],
  "eventos": [
    {
      "id": "e00d0860-fad8-4fc0-aa43-4197cc084bd9",
      "tipo": "CREADA",
      "realizado_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
      "repartidor_id": null,
      "latitud": null,
      "longitud": null,
      "metadatos": {
        "estado": "PENDING",
        "prioridad": "PRIORITY"
      },
      "creado_en": "2026-09-28T14:00:00Z"
    },
    {
      "id": "e891e47f-46bd-4560-9e7b-6b888bd147de",
      "tipo": "ASIGNADA",
      "realizado_por_id": "11932565-95fa-424c-a287-f937978c88cb",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": null,
      "longitud": null,
      "metadatos": {
        "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
        "repartidor_anterior_id": null,
        "tipo_asignacion": "MANUAL"
      },
      "creado_en": "2026-09-28T14:05:00Z"
    },
    {
      "id": "e6318c92-60ec-4a0d-9718-e84795b2b249",
      "tipo": "HACIA_RECOLECCION",
      "realizado_por_id": "ef19583b-459c-491e-becf-8e2f3f407673",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": "14.090100",
      "longitud": "-87.181500",
      "metadatos": {
        "estado_anterior": "ASSIGNED",
        "estado_nuevo": "GOING_TO_PICKUP"
      },
      "creado_en": "2026-09-28T14:10:00Z"
    },
    {
      "id": "e2748f86-c313-4101-82bd-77066df85268",
      "tipo": "LLEGADA_RECOLECCION",
      "realizado_por_id": "ef19583b-459c-491e-becf-8e2f3f407673",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": "14.101200",
      "longitud": "-87.193100",
      "metadatos": {
        "estado_anterior": "GOING_TO_PICKUP",
        "estado_nuevo": "AT_PICKUP"
      },
      "creado_en": "2026-09-28T14:20:00Z"
    }
  ],
  "asignaciones": [
    {
      "id": "f00e36fb-3ef5-481a-b7e8-73e43579c165",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "asignada_por_id": "11932565-95fa-424c-a287-f937978c88cb",
      "tipo": "MANUAL",
      "estado": "ACTIVA",
      "asignada_en": "2026-09-28T14:05:00Z",
      "aceptada_en": "2026-09-28T14:10:00Z",
      "finalizada_en": null,
      "motivo": "Asignación del encargado de turno"
    }
  ],
  "movimiento_especial": null,
  "asignada_en": "2026-09-28T14:05:00Z",
  "llegada_recoleccion_en": "2026-09-28T14:20:00Z",
  "recolectada_en": null,
  "llegada_destino_en": null,
  "entregada_en": null,
  "cancelada_en": null,
  "actualizado_en": "2026-09-28T14:20:00Z"
}
```

Los arreglos se devuelven como `[]` cuando no contienen registros. Los campos
opcionales o las fechas que todavía no aplican se devuelven como `null`; no se
deben interpretar como campos omitidos.

En un envío `ESPECIAL`, `destino` es `null`, `destino_especial` contiene el
texto visible y `presentacion_ruta` vale `SOLO_KILOMETROS`. Mientras está en
curso, `kilometros_envio_especial` es `null`. Al cerrarlo contiene el decimal
con tres posiciones y `movimiento_especial` presenta el detalle congelado:

```json
{
  "id": "97c817eb-cb2d-4370-a02a-a0f47b08f2c4",
  "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "jornada_id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
  "estado": "FINALIZADO",
  "iniciada_en": "2026-09-28T14:30:00Z",
  "finalizada_en": "2026-09-28T15:15:00Z",
  "latitud_inicio": "14.101200",
  "longitud_inicio": "-87.193100",
  "latitud_fin": "14.092100",
  "longitud_fin": "-87.184200",
  "kilometros_recorridos": "8.426",
  "registros_considerados": 84,
  "registros_descartados": 3
}
```

Estados reconocidos por el esquema:

- `PENDING`
- `ASSIGNED`
- `GOING_TO_PICKUP`
- `AT_PICKUP`
- `PICKED_UP`
- `IN_TRANSIT`
- `AT_DESTINATION`
- `DELIVERED`
- `CANCELLED`
- `PICKUP_FAILED`
- `DELIVERY_FAILED`

La creación responde `ASSIGNED` si encontró motorista elegible; si no,
permanece `PENDING` para asignación posterior. La asignación manual también
cambia `PENDING` a `ASSIGNED`; el resto del ciclo se controla mediante el
endpoint de transiciones descrito a continuación.

## 20. Flota, motoristas y asignaciones

Los códigos técnicos de roles permanecen estables:

- `REPARTIDOR_CORPORATIVO`: motorista de Corporate;
- `REPARTIDOR_RED`: motorista de Network;
- `GERENTE_OPERACIONES`: dirección operativa y administración de usuarios
  operativos de Corporate, con alcance exclusivo de empresa;
- `OPERADOR_RED`: encargado operativo de Network.

`SUPERVISOR_CORPORATIVO` fue retirado del catálogo activo. Sus funciones se
integraron en `GERENTE_OPERACIONES` y ya no aparece en roles asignables.

### Vehículos

`GET /api/v1/vehiculos/` acepta los filtros opcionales `empresa_id`, `estado`
y `tipo`. La respuesta usa la paginación estándar.

Respuesta `200` completa del listado:

```json
{
  "conteo": 1,
  "pagina_siguiente": null,
  "pagina_anterior": null,
  "resultados": [
    {
      "id": "9f1c7da2-e2a4-4a86-8bdb-6ddde60a6354",
      "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "placa": "HBA-1234",
      "tipo": "MOTOCICLETA",
      "marca": "Honda",
      "modelo": "XR150",
      "anio": 2026,
      "capacidad_carga_kg": null,
      "estado": "ACTIVO",
      "notas": null,
      "creado_en": "2026-09-28T13:00:00Z",
      "actualizado_en": "2026-09-28T13:00:00Z"
    }
  ]
}
```

`POST /api/v1/vehiculos/` recibe:

```json
{
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "placa": "HBA-1234",
  "tipo": "MOTOCICLETA",
  "marca": "Honda",
  "modelo": "XR150",
  "anio": 2026,
  "estado": "ACTIVO",
  "notas": null
}
```

En Corporate, `empresa_id` es obligatorio. En Network debe omitirse porque la
flota operativa tiene alcance global. La placa se normaliza a mayúsculas y es
única dentro de cada despliegue.

En creación, `tipo` solo admite `MOTOCICLETA`. Los tipos anteriores
(`AUTOMOVIL`, `PANEL`, `ESPECIAL`, `OTRO`) permanecen consultables en registros
históricos, pero no se pueden crear ni asignar a un motorista operativo.
`capacidad_carga_kg` no se envía en `POST`: es obsoleto, no editable y no
obligatorio. En respuestas puede seguir como `null` o conservar el valor
histórico de vehículos antiguos.

Estados: `ACTIVO`, `MANTENIMIENTO`, `FUERA_SERVICIO`, `INACTIVO`.

`POST /api/v1/vehiculos/` responde `201` y
`GET /api/v1/vehiculos/{vehiculo_id}/` responde `200` con el mismo objeto
completo:

```json
{
  "id": "9f1c7da2-e2a4-4a86-8bdb-6ddde60a6354",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "placa": "HBA-1234",
  "tipo": "MOTOCICLETA",
  "marca": "Honda",
  "modelo": "XR150",
  "anio": 2026,
  "capacidad_carga_kg": null,
  "estado": "ACTIVO",
  "notas": null,
  "creado_en": "2026-09-28T13:00:00Z",
  "actualizado_en": "2026-09-28T13:00:00Z"
}
```

En Network, `empresa_id` se devuelve como `null`. `marca`, `modelo`, `anio`,
`capacidad_carga_kg` (obsoleto) y `notas` también pueden ser `null`. Los
decimales históricos se representan como texto.

### Motoristas

`POST /api/v1/repartidores/` crea el perfil operativo de un usuario existente:

```json
{
  "usuario_id": "ef19583b-459c-491e-becf-8e2f3f407673",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "vehiculo_id": "9f1c7da2-e2a4-4a86-8bdb-6ddde60a6354"
}
```

El usuario debe estar activo y poseer previamente el rol técnico de motorista.
En Corporate el rol y el vehículo deben pertenecer a la misma empresa. En
Network tanto el rol como el perfil tienen alcance global.

El perfil nace con:

```json
{
  "estado_operativo": "OFFLINE",
  "capacidad": "EMPTY",
  "activo": true
}
```

`GET /api/v1/repartidores/` acepta `empresa_id`, `estado_operativo`,
`capacidad` (calculada) y `activo`. `GET /api/v1/repartidores/disponibles/`
devuelve motoristas activos, con usuario y motocicleta activos, estado
`AVAILABLE` o `ON_ROUTE` con al menos una solicitud activa, menos de cinco
solicitudes activas y sin una solicitud prioritaria activa ni un envío
especial exclusivo en curso.

Ambos listados usan el mismo sobre paginado y el mismo objeto de motorista.
Ejemplo `200`:

```json
{
  "conteo": 1,
  "pagina_siguiente": null,
  "pagina_anterior": null,
  "resultados": [
    {
      "id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "usuario": {
        "id": "ef19583b-459c-491e-becf-8e2f3f407673",
        "correo": "motorista@analiza.com",
        "nombres": "Carlos",
        "apellidos": "Mendoza",
        "telefono": "+50499990000",
        "estado": "ACTIVO"
      },
      "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
      "vehiculo": {
        "id": "9f1c7da2-e2a4-4a86-8bdb-6ddde60a6354",
        "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
        "placa": "HBA-1234",
        "tipo": "MOTOCICLETA",
        "marca": "Honda",
        "modelo": "XR150",
        "anio": 2026,
        "capacidad_carga_kg": null,
        "estado": "ACTIVO",
        "notas": null,
        "creado_en": "2026-09-28T13:00:00Z",
        "actualizado_en": "2026-09-28T13:00:00Z"
      },
      "estado_operativo": "AVAILABLE",
      "capacidad": "EMPTY",
      "solicitudes_activas": 0,
      "limite_solicitudes": 5,
      "puede_recibir_solicitudes": true,
      "activo": true,
      "creado_en": "2026-09-28T13:15:00Z",
      "actualizado_en": "2026-09-28T13:20:00Z"
    }
  ]
}
```

`POST /api/v1/repartidores/` responde `201`, mientras
`GET /api/v1/repartidores/{repartidor_id}/` y el `PATCH` operativo responden
`200`. Los tres devuelven el mismo objeto completo, sin sobre de paginación:

```json
{
  "id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "usuario": {
    "id": "ef19583b-459c-491e-becf-8e2f3f407673",
    "correo": "motorista@analiza.com",
    "nombres": "Carlos",
    "apellidos": "Mendoza",
    "telefono": "+50499990000",
    "estado": "ACTIVO"
  },
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "vehiculo": {
    "id": "9f1c7da2-e2a4-4a86-8bdb-6ddde60a6354",
    "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
    "placa": "HBA-1234",
    "tipo": "MOTOCICLETA",
    "marca": "Honda",
    "modelo": "XR150",
    "anio": 2026,
    "capacidad_carga_kg": null,
    "estado": "ACTIVO",
    "notas": null,
    "creado_en": "2026-09-28T13:00:00Z",
    "actualizado_en": "2026-09-28T13:00:00Z"
  },
  "estado_operativo": "AVAILABLE",
  "capacidad": "EMPTY",
  "solicitudes_activas": 0,
  "limite_solicitudes": 5,
  "puede_recibir_solicitudes": true,
  "activo": true,
  "creado_en": "2026-09-28T13:15:00Z",
  "actualizado_en": "2026-09-28T13:20:00Z"
}
```

`vehiculo` es `null` si todavía no fue asignado. En Network,
`empresa_id` es `null` tanto en el motorista como en su vehículo. El campo
`telefono` del usuario también puede ser `null` o texto vacío.

El motorista consulta sus propios datos sin conocer previamente su UUID:

```http
GET /api/v1/repartidores/mi-perfil/
Authorization: Bearer <token>
```

Devuelve `200` con el mismo objeto completo de motorista mostrado arriba:
`id`, `usuario`, `empresa_id`, `vehiculo`, `estado_operativo`, `capacidad`,
`solicitudes_activas`, `limite_solicitudes`, `puede_recibir_solicitudes`,
`activo` y marcas de tiempo. Solo busca el perfil asociado al usuario
autenticado; no requiere `repartidor.ver` ni permite consultar otros perfiles.
Si el usuario no tiene un perfil activo de motorista, responde `404`. Esta
ruta no cambia `GET /api/v1/usuarios/mi-perfil/`.

Estados operativos: `OFFLINE`, `AVAILABLE`, `ON_ROUTE`, `PAUSED`,
`OUT_OF_SERVICE`.

Capacidades: `EMPTY`, `AVAILABLE_SPACE`, `FULL`.

Para modificar el estado operativo:

```http
PATCH /api/v1/repartidores/{repartidor_id}/operacion/
```

```json
{
  "estado_operativo": "AVAILABLE",
  "motivo": "Inicio de operación"
}
```

Permisos exactos del `PATCH`:

| Objetivo | Campos enviados | Permiso obligatorio |
|---|---|---|
| Perfil propio | `estado_operativo` | `repartidor.actualizar_estado` |
| Otro motorista | `estado_operativo` | `repartidor.administrar` dentro del alcance del motorista |

Los roles `REPARTIDOR_CORPORATIVO` y `REPARTIDOR_RED` reciben el permiso de
actualización del estado propio. `SUPERADMINISTRADOR`,
`ADMINISTRADOR_CORPORATIVO`, `GERENTE_OPERACIONES` y `OPERADOR_RED` incluyen
`repartidor.administrar`, sujeto al alcance de su asignación de rol.

Si un usuario modifica su propio perfil, el backend exige el permiso específico
de estado aunque también tenga un rol administrativo. Debe enviar
`estado_operativo`; `motivo` es opcional. Enviar `capacidad` produce `400`:
la capacidad manual y el permiso `repartidor.actualizar_capacidad` son
obsoletos. `EMPTY` significa cero solicitudes activas,
`AVAILABLE_SPACE` entre una y cuatro, y `FULL` cinco. El backend recalcula
estos valores al asignar, reasignar, cancelar, fallar o finalizar una solicitud.
Los estados activos son `ASSIGNED`, `GOING_TO_PICKUP`, `AT_PICKUP`,
`PICKED_UP`, `IN_TRANSIT` y `AT_DESTINATION`; `PENDING` y los terminales no
cuentan. No se acepta un cambio operativo sin efecto. Para quedar `AVAILABLE`
se requiere motocicleta activa. Todo cambio efectivo queda en historial.

### Asignación automática en Corporate

`POST /api/v1/solicitudes/` intenta asignar inmediatamente la solicitud al
motorista elegible más cercano al origen. Usa la distancia GPS en línea recta
entre el último punto registrado del motorista y el origen; **no** es
distancia vial, ETA ni una llamada a Google Maps. Solo considera perfiles
activos de la misma empresa, con usuario y motocicleta activos, estado
`AVAILABLE` o `ON_ROUTE` con carga activa, menos de cinco solicitudes, sin
prioritario activo ni envío especial exclusivo. Las cuentas de prueba siguen
las mismas reglas.

Los motoristas sin GPS registrado quedan después de quienes sí tienen punto;
entre empates se usa un orden estable. Antes de asignar, el backend bloquea
la fila del motorista y vuelve a validar todas las restricciones. Si un
candidato dejó de estar disponible, continúa con el siguiente. La asignación
se registra como `AUTOMATICA`, actualiza el cupo y genera una notificación
persistente **solo para el motorista finalmente asignado**. No existe
aceptación, rechazo ni temporizador del motorista.
En una asignación automática, `asignada_por_id` conserva al usuario que creó
la solicitud y `tipo: "AUTOMATICA"` deja claro que la elección del motorista
la hizo el backend.

Si nadie es elegible, la creación sigue respondiendo `201` con
`estado: "PENDING"` y `repartidor_asignado_id: null`; no se crea una
notificación. Las solicitudes pendientes anteriores a este cambio no se
reasignan retroactivamente. Para que el aviso aparezca en el teléfono, el
frontend debe consultar `/api/v1/notificaciones/` o integrar push en una fase
posterior.

### Asignación manual

```http
POST /api/v1/solicitudes/{solicitud_id}/asignaciones/
```

```json
{
  "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "motivo": "Asignación del encargado de turno"
}
```

`repartidor_id` es el `id` del perfil devuelto por
`GET /api/v1/repartidores/disponibles/`, **no** `usuario.id`. El listado ya no
interpreta la ausencia del filtro opcional `activo` como `false`.

Reglas:

- la primera asignación requiere `solicitud.asignar`;
- cambiar de motorista requiere `solicitud.reasignar`;
- la solicitud debe estar `PENDING` o `ASSIGNED`;
- el motorista debe estar activo, con motocicleta activa y estado `AVAILABLE`,
  o `ON_ROUTE` si ya atiende solicitudes y aún puede recibir otra;
- el máximo es cinco solicitudes activas, controlado exclusivamente en el
  backend; al intentar una sexta se responde `409` con
  `{"repartidor_id":["El motorista ya tiene cinco solicitudes activas."]}`;
- Corporate exige la misma empresa; Network exige un motorista global;
- un motorista con una solicitud `PRIORITY` activa no recibe otra;
- la operación bloquea las filas involucradas y se ejecuta atómicamente;
- una reasignación cierra la asignación anterior y conserva todo el historial;
- se crea el evento `ASIGNADA` o `REASIGNADA`;
- la respuesta `201` contiene el detalle actualizado de la solicitud.

Los resúmenes de solicitud incluyen `repartidor_asignado_id`. El detalle
incluye además `asignaciones`, con su estado, responsable, fechas y motivo. Un
motorista con `solicitud.ver_asignadas` solo obtiene solicitudes cuyo
`repartidor_asignado_id` sigue apuntando a su perfil, incluidas las terminadas
sin reasignación. Si se reasigna una solicitud, el motorista anterior deja de
verla aunque figure en el historial de asignaciones.

Respuesta `201` completa de una primera asignación:

```json
{
  "id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "numero": "SOL-20260928-BF9490A0",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": "d2c7775a-8223-4cf7-b23b-e11caf453120",
  "solicitada_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
  "repartidor_asignado_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "prioridad": "PRIORITY",
  "tipo_servicio": {
    "id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
    "codigo": "MUESTRA_BIOLOGICA",
    "nombre": "Muestra biológica",
    "descripcion": "Traslado controlado de muestras biológicas."
  },
  "origen": {
    "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
    "nombre": "Laboratorio Central",
    "direccion": "Colonia Palmira, Tegucigalpa",
    "latitud": "14.101200",
    "longitud": "-87.193100"
  },
  "destino": {
    "id": "3c18fa32-7bc2-4743-9744-f22453730413",
    "nombre": "Hospital Principal",
    "direccion": "Bulevar Suyapa, Tegucigalpa",
    "latitud": "14.085600",
    "longitud": "-87.165400"
  },
  "estado": "ASSIGNED",
  "creado_en": "2026-09-28T14:00:00Z",
  "notas": "Entregar directamente en recepción.",
  "articulos": [
    {
      "id": "9067300c-8cb8-44e6-9fe5-145fcb5adef1",
      "tipo_articulo": "Muestra de laboratorio",
      "descripcion": "Contenedor sellado",
      "cantidad": "2.00",
      "codigo_referencia": "LAB-2026-001",
      "condicion_transporte": "Temperatura controlada",
      "notas": null
    }
  ],
  "eventos": [
    {
      "id": "e00d0860-fad8-4fc0-aa43-4197cc084bd9",
      "tipo": "CREADA",
      "realizado_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
      "repartidor_id": null,
      "latitud": null,
      "longitud": null,
      "metadatos": {
        "estado": "PENDING",
        "prioridad": "PRIORITY"
      },
      "creado_en": "2026-09-28T14:00:00Z"
    },
    {
      "id": "e891e47f-46bd-4560-9e7b-6b888bd147de",
      "tipo": "ASIGNADA",
      "realizado_por_id": "11932565-95fa-424c-a287-f937978c88cb",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": null,
      "longitud": null,
      "metadatos": {
        "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
        "repartidor_anterior_id": null,
        "tipo_asignacion": "MANUAL"
      },
      "creado_en": "2026-09-28T14:05:00Z"
    }
  ],
  "asignaciones": [
    {
      "id": "f00e36fb-3ef5-481a-b7e8-73e43579c165",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "asignada_por_id": "11932565-95fa-424c-a287-f937978c88cb",
      "tipo": "MANUAL",
      "estado": "ACTIVA",
      "asignada_en": "2026-09-28T14:05:00Z",
      "aceptada_en": null,
      "finalizada_en": null,
      "motivo": "Asignación del encargado de turno"
    }
  ],
  "asignada_en": "2026-09-28T14:05:00Z",
  "llegada_recoleccion_en": null,
  "recolectada_en": null,
  "llegada_destino_en": null,
  "entregada_en": null,
  "cancelada_en": null,
  "actualizado_en": "2026-09-28T14:05:00Z"
}
```

Estados de una asignación:

| Estado | Cuándo se utiliza |
|---|---|
| `ACTIVA` | Es la asignación vigente de la solicitud. |
| `REASIGNADA` | Fue reemplazada por otra asignación; conserva `finalizada_en`. |
| `FINALIZADA` | La solicitud terminó como `DELIVERED`. |
| `CANCELADA` | La solicitud terminó como `CANCELLED`, `PICKUP_FAILED` o `DELIVERY_FAILED`. |

El tipo devuelto actualmente por el endpoint manual es `MANUAL`.
`AUTOMATICA` está reservado en el esquema para un asignador futuro. La
primera transición a `GOING_TO_PICKUP` establece `aceptada_en`; cerrar,
fallar, cancelar o reasignar establece `finalizada_en`.

## 21. Operación y evidencias

### Transiciones de solicitud

```http
POST /api/v1/solicitudes/{solicitud_id}/transiciones/
Content-Type: application/json
```

Ejemplo:

```json
{
  "estado_destino": "AT_PICKUP",
  "latitud": "14.072300",
  "longitud": "-87.192100",
  "motivo": null
}
```

`latitud` y `longitud` son opcionales, pero deben enviarse juntas. `motivo` es
obligatorio para `CANCELLED`, `PICKUP_FAILED` y `DELIVERY_FAILED`.

Secuencia normal permitida:

```text
ASSIGNED -> GOING_TO_PICKUP -> AT_PICKUP -> PICKED_UP
         -> IN_TRANSIT -> AT_DESTINATION -> DELIVERED
```

Matriz exacta aceptada por el backend:

| Estado actual | Estados destino permitidos |
|---|---|
| `PENDING` | `CANCELLED` |
| `ASSIGNED` | `GOING_TO_PICKUP`, `CANCELLED` |
| `GOING_TO_PICKUP` | `AT_PICKUP`, `CANCELLED`, `PICKUP_FAILED` |
| `AT_PICKUP` | `PICKED_UP`, `CANCELLED`, `PICKUP_FAILED` |
| `PICKED_UP` | `IN_TRANSIT`, `DELIVERY_FAILED` |
| `IN_TRANSIT` | `AT_DESTINATION`, `DELIVERY_FAILED` |
| `AT_DESTINATION` | `DELIVERED`, `DELIVERY_FAILED` |
| `DELIVERED` | Ninguno; estado terminal. |
| `CANCELLED` | Ninguno; estado terminal. |
| `PICKUP_FAILED` | Ninguno; estado terminal. |
| `DELIVERY_FAILED` | Ninguno; estado terminal. |

Reglas adicionales:

- solo el motorista actualmente asignado puede realizar transiciones
  operativas;
- `PICKED_UP` requiere una evidencia `FOTO_RECOLECCION` de ese motorista;
- `DELIVERED` requiere una evidencia `FOTO_ENTREGA` de ese motorista;
- `PICKUP_FAILED` se admite desde `GOING_TO_PICKUP` o `AT_PICKUP`;
- `DELIVERY_FAILED` se admite desde `PICKED_UP`, `IN_TRANSIT` o
  `AT_DESTINATION`;
- `CANCELLED` requiere `solicitud.cancelar` y solo se admite antes de que el
  contenido haya sido recolectado;
- las transiciones inválidas responden `400`;
- iniciar el desplazamiento cambia al motorista a `ON_ROUTE`;
- un estado terminal cierra la asignación. Si no quedan otras asignaciones
  activas, el motorista vuelve a `AVAILABLE` con capacidad `EMPTY`, excepto si
  ya estaba en pausa, desconectado o fuera de servicio;
- cada cambio genera un evento auditable con estado anterior, estado nuevo,
  responsable y GPS cuando fue enviado.
- para `ESPECIAL`, la transición a `PICKED_UP` exige `latitud` y `longitud`,
  una jornada activa y ausencia de otras asignaciones activas; en ese momento
  abre el movimiento y deja al motorista `ON_ROUTE`. `FULL` solo significa
  cinco solicitudes activas, incluso para un envío especial;
- mientras ese movimiento está activo no se pueden asignar otras solicitudes
  al motorista;
- para `ESPECIAL`, `DELIVERED` y `DELIVERY_FAILED` también exigen coordenadas;
  cierran el movimiento y congelan el kilometraje calculado con los puntos GPS;
- antes de cerrar, el dispositivo debe enviar su lote GPS pendiente. Los
  puntos retrasados se conservan, pero no alteran un kilometraje ya congelado.

Permisos exactos:

- toda transición distinta de `CANCELLED` exige que el usuario sea el
  motorista actualmente asignado y tenga `solicitud.actualizar_estado` dentro
  del alcance de la solicitud;
- `CANCELLED` no exige ser el motorista, pero sí requiere
  `solicitud.cancelar` dentro del alcance de la solicitud;
- poseer `solicitud.actualizar_estado` no permite operar una solicitud
  asignada a otro motorista;
- poseer `solicitud.cancelar` no permite saltarse la matriz de estados.

La respuesta `200` contiene el detalle actualizado completo de la solicitud.
Todos los endpoints que devuelven detalle incluyen también `modalidad`,
`destino_especial`, `presentacion_ruta`, `kilometros_envio_especial` y
`movimiento_especial`, aunque los ejemplos operativos generales muestren una
solicitud no especial.
Ejemplo después de avanzar a `AT_PICKUP`:

```json
{
  "id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "numero": "SOL-20260928-BF9490A0",
  "empresa_id": "3b0407a3-bc31-4d31-9619-7a3f01ac0b96",
  "sucursal_id": "d2c7775a-8223-4cf7-b23b-e11caf453120",
  "solicitada_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
  "repartidor_asignado_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "prioridad": "PRIORITY",
  "tipo_servicio": {
    "id": "8814652b-d743-4385-9cd9-32e66a9c2d5d",
    "codigo": "MUESTRA_BIOLOGICA",
    "nombre": "Muestra biológica",
    "descripcion": "Traslado controlado de muestras biológicas."
  },
  "origen": {
    "id": "2de2d88f-65b5-4e3e-951f-0f6faf8002e3",
    "nombre": "Laboratorio Central",
    "direccion": "Colonia Palmira, Tegucigalpa",
    "latitud": "14.101200",
    "longitud": "-87.193100"
  },
  "destino": {
    "id": "3c18fa32-7bc2-4743-9744-f22453730413",
    "nombre": "Hospital Principal",
    "direccion": "Bulevar Suyapa, Tegucigalpa",
    "latitud": "14.085600",
    "longitud": "-87.165400"
  },
  "estado": "AT_PICKUP",
  "creado_en": "2026-09-28T14:00:00Z",
  "notas": "Entregar directamente en recepción.",
  "articulos": [
    {
      "id": "9067300c-8cb8-44e6-9fe5-145fcb5adef1",
      "tipo_articulo": "Muestra de laboratorio",
      "descripcion": "Contenedor sellado",
      "cantidad": "2.00",
      "codigo_referencia": "LAB-2026-001",
      "condicion_transporte": "Temperatura controlada",
      "notas": null
    }
  ],
  "eventos": [
    {
      "id": "e00d0860-fad8-4fc0-aa43-4197cc084bd9",
      "tipo": "CREADA",
      "realizado_por_id": "8429ba3a-d32f-4696-bb70-d3b48ef47f30",
      "repartidor_id": null,
      "latitud": null,
      "longitud": null,
      "metadatos": {
        "estado": "PENDING",
        "prioridad": "PRIORITY"
      },
      "creado_en": "2026-09-28T14:00:00Z"
    },
    {
      "id": "e891e47f-46bd-4560-9e7b-6b888bd147de",
      "tipo": "ASIGNADA",
      "realizado_por_id": "11932565-95fa-424c-a287-f937978c88cb",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": null,
      "longitud": null,
      "metadatos": {
        "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
        "repartidor_anterior_id": null,
        "tipo_asignacion": "MANUAL"
      },
      "creado_en": "2026-09-28T14:05:00Z"
    },
    {
      "id": "e6318c92-60ec-4a0d-9718-e84795b2b249",
      "tipo": "HACIA_RECOLECCION",
      "realizado_por_id": "ef19583b-459c-491e-becf-8e2f3f407673",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": "14.090100",
      "longitud": "-87.181500",
      "metadatos": {
        "estado_anterior": "ASSIGNED",
        "estado_nuevo": "GOING_TO_PICKUP"
      },
      "creado_en": "2026-09-28T14:10:00Z"
    },
    {
      "id": "e2748f86-c313-4101-82bd-77066df85268",
      "tipo": "LLEGADA_RECOLECCION",
      "realizado_por_id": "ef19583b-459c-491e-becf-8e2f3f407673",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": "14.101200",
      "longitud": "-87.193100",
      "metadatos": {
        "estado_anterior": "GOING_TO_PICKUP",
        "estado_nuevo": "AT_PICKUP"
      },
      "creado_en": "2026-09-28T14:20:00Z"
    }
  ],
  "asignaciones": [
    {
      "id": "f00e36fb-3ef5-481a-b7e8-73e43579c165",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "asignada_por_id": "11932565-95fa-424c-a287-f937978c88cb",
      "tipo": "MANUAL",
      "estado": "ACTIVA",
      "asignada_en": "2026-09-28T14:05:00Z",
      "aceptada_en": "2026-09-28T14:10:00Z",
      "finalizada_en": null,
      "motivo": "Asignación del encargado de turno"
    }
  ],
  "asignada_en": "2026-09-28T14:05:00Z",
  "llegada_recoleccion_en": "2026-09-28T14:20:00Z",
  "recolectada_en": null,
  "llegada_destino_en": null,
  "entregada_en": null,
  "cancelada_en": null,
  "actualizado_en": "2026-09-28T14:20:00Z"
}
```

### Registrar evidencia

```http
POST /api/v1/solicitudes/{solicitud_id}/evidencias/
Content-Type: multipart/form-data
```

Campos:

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `tipo` | texto | Sí | `FOTO_RECOLECCION`, `FOTO_ENTREGA` o `FOTO_INCIDENCIA`. |
| `archivo` | archivo | Sí | Imagen JPEG, PNG o WebP, máximo 10 MB por configuración local. |
| `latitud` | decimal | Sí | Coordenada de captura entre -90 y 90. |
| `longitud` | decimal | Sí | Coordenada de captura entre -180 y 180. |
| `capturada_en` | fecha ISO 8601 | Sí | Momento real de captura informado por el dispositivo. |
| `notas` | texto | No | Observaciones operativas. |

La foto de recolección solo se acepta en `AT_PICKUP`; la foto de entrega solo
se acepta en `AT_DESTINATION`. Una foto de incidencia se acepta mientras exista
una operación asignada y no terminal. El backend comprueba que el tipo declarado
coincida con la firma básica del archivo.

Respuesta `201`:

```json
{
  "id": "6c85b340-0e6f-4c0e-9708-f83ffdf2f35a",
  "solicitud_id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "tipo": "FOTO_RECOLECCION",
  "tipo_contenido": "image/jpeg",
  "tamano_bytes": 248731,
  "latitud": "14.072300",
  "longitud": "-87.192100",
  "capturada_en": "2026-09-26T14:15:00Z",
  "notas": null,
  "archivo_disponible": true,
  "creado_en": "2026-09-26T14:15:03Z"
}
```

La respuesta no expone la clave interna ni una URL pública.

### Consultar evidencias

```http
GET /api/v1/solicitudes/{solicitud_id}/evidencias/
```

Devuelve el sobre paginado estándar con objetos del formato anterior. Requiere
visibilidad de la solicitud y `evidencia.ver` en su alcance.

Para mostrar una imagen:

```http
GET /api/v1/solicitudes/{solicitud_id}/evidencias/{evidencia_id}/archivo/
```

El frontend debe enviar el Bearer token y consumir el cuerpo binario usando el
`Content-Type` de la respuesta. El archivo usa caché privada deshabilitada y no
debe tratarse como una URL pública permanente.

## 22. Jornadas de motoristas

### Iniciar jornada

```http
POST /api/v1/jornadas/iniciar/
```

Las coordenadas son opcionales. Si están disponibles deben enviarse juntas:

```json
{
  "latitud": "14.072300",
  "longitud": "-87.192100"
}
```

También se permite un objeto vacío. El motorista necesita perfil, usuario y
vehículo activos, además de `jornada.iniciar`. Su estado debe ser `OFFLINE` o
`AVAILABLE`. Solo puede existir una jornada activa por motorista.

La respuesta `201` contiene:

```json
{
  "id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
  "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "estado": "ACTIVA",
  "iniciada_en": "2026-09-26T14:30:00Z",
  "finalizada_en": null,
  "latitud_inicio": "14.072300",
  "longitud_inicio": "-87.192100",
  "latitud_fin": null,
  "longitud_fin": null,
  "kilometros_operativos": "0.000",
  "kilometraje_disponible": false,
  "servicios_completados": 0,
  "recolecciones_completadas": 0,
  "entregas_completadas": 0,
  "servicios_normales": 0,
  "servicios_prioritarios": 0,
  "minutos_activos": 0,
  "incidencias_reportadas": 0,
  "incidencias_disponibles": true,
  "creado_en": "2026-09-26T14:30:00Z",
  "actualizado_en": "2026-09-26T14:30:00Z"
}
```

El inicio cambia al motorista a `AVAILABLE` y registra el cambio en su
historial operativo.

### Consultar jornada activa

```http
GET /api/v1/jornadas/activa/
```

Para un motorista autenticado con perfil activo y `jornada.ver` responde
`200`. Sin ese permiso responde `403`; sin perfil activo, `404`. Cuando existe
una jornada devuelve:

```json
{
  "jornada": {
    "id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
    "estado": "ACTIVA"
  }
}
```

El objeto real contiene todos los campos del ejemplo anterior. Si no existe:

```json
{
  "jornada": null
}
```

### Historial y detalle

```http
GET /api/v1/jornadas/
GET /api/v1/jornadas/{jornada_id}/
```

El listado utiliza la paginación estándar y acepta:

| Parámetro | Descripción |
|---|---|
| `repartidor_id` | UUID del motorista. |
| `estado` | `ACTIVA` o `FINALIZADA`. |
| `desde` | Fecha y hora ISO 8601 mínima de inicio. |
| `hasta` | Fecha y hora ISO 8601 máxima de inicio. |

Un motorista solo recibe sus jornadas. Encargados y administradores con
`repartidor.administrar` y `jornada.ver` pueden consultar las jornadas dentro
de su alcance.

### Finalizar jornada

```http
POST /api/v1/jornadas/{jornada_id}/finalizar/
```

Acepta las coordenadas finales opcionales con el mismo formato del inicio.
Solo el motorista propietario puede finalizarla y no debe conservar ninguna
asignación `ACTIVA`.

Al finalizar, el backend:

- cambia la jornada a `FINALIZADA`;
- calcula y congela servicios, recolecciones, entregas, normales,
  prioritarios y minutos activos;
- cambia al motorista a `OFFLINE` con capacidad `EMPTY`;
- conserva el historial y no permite eliminar la jornada.

Mientras no esté implementado el cálculo de kilometraje,
`kilometraje_disponible=false` y `kilometros_operativos="0.000"`. Las
incidencias ya se calculan desde su módulo operativo, por lo que
`incidencias_disponibles=true`. El frontend no debe presentar el kilometraje
cero como una medición definitiva.

## 23. Seguimiento GPS

Esta primera fase no llama a Google Maps. El dispositivo obtiene las
coordenadas mediante su sistema operativo y las envía a VitaGo. El backend
conserva los puntos, determina si pertenecen a una operación y limita su
consulta al contexto de una solicitud autorizada.

### Registrar ubicaciones

```http
POST /api/v1/seguimiento/registros/
Content-Type: application/json
```

Solo puede utilizarlo el motorista autenticado con el permiso
`repartidor.registrar_ubicacion`. La jornada debe pertenecerle. Se aceptan
puntos retrasados siempre que `registrada_en` se encuentre dentro del intervalo
de la jornada. Cada lote admite entre 1 y 200 registros.

```json
{
  "jornada_id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
  "registros": [
    {
      "id_cliente": "bd1a0f90-c321-44c4-a3a8-8aa9ca80dc51",
      "latitud": "14.072300",
      "longitud": "-87.192100",
      "precision_metros": "8.50",
      "velocidad_metros_segundo": "4.250",
      "rumbo_grados": "180.00",
      "registrada_en": "2026-09-26T15:10:00Z"
    }
  ]
}
```

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `id_cliente` | UUID | Sí | Identificador estable generado por el dispositivo para reintentos. |
| `latitud` | decimal | Sí | Entre -90 y 90. |
| `longitud` | decimal | Sí | Entre -180 y 180. |
| `precision_metros` | decimal | No | Mayor o igual que cero. |
| `velocidad_metros_segundo` | decimal | No | Mayor o igual que cero. |
| `rumbo_grados` | decimal | No | Desde 0 hasta 359.99. |
| `registrada_en` | fecha ISO 8601 | Sí | Hora real del punto en el dispositivo. |

La combinación de motorista e `id_cliente` es única. Repetir exactamente el
mismo registro no crea otra fila. Reutilizar el identificador con valores
distintos responde `400`.

Respuesta `201`:

```json
{
  "recibidos": 1,
  "creados": 1,
  "repetidos": 0,
  "registros": [
    {
      "id": "377618eb-38b6-4247-8a90-89cd0f497f55",
      "id_cliente": "bd1a0f90-c321-44c4-a3a8-8aa9ca80dc51",
      "jornada_id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
      "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
      "latitud": "14.072300",
      "longitud": "-87.192100",
      "precision_metros": "8.50",
      "velocidad_metros_segundo": "4.250",
      "rumbo_grados": "180.00",
      "registrada_en": "2026-09-26T15:10:00Z",
      "es_operativo": true,
      "movimiento_envio_especial_id": null,
      "creado_en": "2026-09-26T15:10:03Z"
    }
  ]
}
```

`es_operativo` lo calcula exclusivamente el backend. Es verdadero cuando el
momento del punto cae dentro de una asignación aceptada y aún no finalizada del
motorista. El frontend no debe enviarlo ni calcularlo.

Para tolerar pérdidas de red, la aplicación puede guardar localmente los puntos
pendientes y reenviar el mismo `id_cliente`. Debe retirar de su cola los
registros incluidos en una respuesta correcta.

Durante un envío especial, `movimiento_envio_especial_id` contiene el UUID del
movimiento. El backend descarta del cálculo los puntos cuya precisión supere
`PRECISION_GPS_MAXIMA_METROS` o que impliquen una velocidad superior a
`VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO`. Los valores predeterminados locales son
100 metros y 55 metros por segundo. Google Maps no participa en este cálculo.

### Consultar seguimiento de una solicitud

```http
GET /api/v1/solicitudes/{solicitud_id}/seguimiento/
```

La consulta exige visibilidad sobre la solicitud y el permiso
`solicitud.ver_seguimiento` dentro de su alcance. No existe un endpoint abierto
para consultar directamente la ubicación de un motorista.

Respuesta `200` durante una solicitud activa:

```json
{
  "solicitud_id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "estado": "IN_TRANSIT",
  "seguimiento_disponible": true,
  "ubicacion": {
    "id": "377618eb-38b6-4247-8a90-89cd0f497f55",
    "id_cliente": "bd1a0f90-c321-44c4-a3a8-8aa9ca80dc51",
    "jornada_id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
    "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
    "latitud": "14.072300",
    "longitud": "-87.192100",
    "precision_metros": "8.50",
    "velocidad_metros_segundo": "4.250",
    "rumbo_grados": "180.00",
    "registrada_en": "2026-09-26T15:10:00Z",
    "es_operativo": true,
    "movimiento_envio_especial_id": null,
    "creado_en": "2026-09-26T15:10:03Z"
  }
}
```

Si todavía no existe un punto operativo, `ubicacion` es `null`. Cuando la
solicitud termina, se cancela o falla, el backend responde
`seguimiento_disponible=false` y `ubicacion=null`, aunque el usuario conserve
acceso al detalle histórico de la solicitud.

La primera integración puede consultar este endpoint periódicamente. Aún no se
usan WebSockets, Redis, Google Routes ni Google Roads. El kilometraje general
de la jornada no se calcula. En cambio, los puntos GPS del movimiento
`ESPECIAL` sí permiten calcular sus kilómetros al cerrarlo, aplicando los
filtros de precisión y velocidad descritos arriba.

## 24. Incidencias operativas

### Reportar una incidencia

```http
POST /api/v1/incidencias/
Content-Type: application/json
```

Solo el motorista autenticado con `incidencia.crear` puede reportar durante su
jornada activa. La solicitud es opcional; cuando se proporciona, el backend
comprueba que estuviera asignada al motorista en el momento indicado.

```json
{
  "solicitud_id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "descripcion": "La calle de acceso está cerrada por trabajos.",
  "latitud": "14.072300",
  "longitud": "-87.192100",
  "reportada_en": "2026-09-26T16:10:00Z"
}
```

`solicitud_id`, `latitud` y `longitud` son opcionales. Las coordenadas deben
enviarse juntas. `descripcion` y `reportada_en` son obligatorios. La fecha debe
pertenecer al intervalo ya transcurrido de la jornada activa.

Respuesta `201`:

```json
{
  "id": "79763994-ef14-453c-b80e-987b3e11d95f",
  "jornada_id": "9f106ce2-050c-4ef7-ab94-446207b8499e",
  "repartidor_id": "a465f3ae-a12b-4972-ae27-8076480f3773",
  "solicitud_id": "bf9490a0-aeb4-4df5-8bd1-8c1341ddfeac",
  "estado": "ABIERTA",
  "descripcion": "La calle de acceso está cerrada por trabajos.",
  "latitud": "14.072300",
  "longitud": "-87.192100",
  "reportada_en": "2026-09-26T16:10:00Z",
  "revisada_por_id": null,
  "revisada_en": null,
  "cerrada_en": null,
  "eventos": [
    {
      "tipo": "REPORTADA",
      "estado_anterior": null,
      "estado_nuevo": "ABIERTA"
    }
  ]
}
```

El objeto real de cada evento también contiene `id`, `realizado_por_id`,
`notas`, `metadatos` y `creado_en`.

### Consultar incidencias

```http
GET /api/v1/incidencias/
GET /api/v1/incidencias/{incidencia_id}/
```

El listado usa el sobre paginado estándar y acepta `estado`, `jornada_id`,
`solicitud_id` y `repartidor_id`. Un motorista solo puede consultar sus propias
incidencias. Gerentes de operaciones y administradores con `incidencia.revisar` consultan
únicamente el alcance organizacional permitido.

Estados disponibles:

- `ABIERTA`;
- `EN_REVISION`;
- `CERRADA`.

### Revisar o cerrar una incidencia

```http
POST /api/v1/incidencias/{incidencia_id}/revision/
Content-Type: application/json
```

Requiere `incidencia.revisar` dentro del alcance del motorista.

```json
{
  "estado": "EN_REVISION",
  "notas": "El supervisor está verificando el cierre de la calle."
}
```

Transiciones permitidas:

```text
ABIERTA -> EN_REVISION -> CERRADA
ABIERTA ----------------> CERRADA
```

Cada transición conserva responsable, fecha, estado anterior, estado nuevo y
notas. Una incidencia cerrada no se reabre ni se elimina.

### Evidencias de incidencia

```http
GET  /api/v1/incidencias/{incidencia_id}/evidencias/
POST /api/v1/incidencias/{incidencia_id}/evidencias/
GET  /api/v1/incidencias/{incidencia_id}/evidencias/{evidencia_id}/archivo/
```

El registro utiliza `multipart/form-data` con:

| Campo | Tipo | Obligatorio |
|---|---|---|
| `archivo` | JPEG, PNG o WebP | Sí |
| `latitud` | decimal entre -90 y 90 | Sí |
| `longitud` | decimal entre -180 y 180 | Sí |
| `capturada_en` | fecha ISO 8601 dentro de la jornada | Sí |
| `notas` | texto | No |

Solo el motorista que reportó la incidencia puede agregar evidencia y no puede
hacerlo después del cierre. La imagen respeta el tamaño máximo configurado para
evidencias. Los archivos son privados, requieren Bearer token para descargarse
y nunca exponen su clave interna de almacenamiento.

Al finalizar una jornada, `incidencias_reportadas` se calcula contando las
incidencias relacionadas directamente con ella y queda congelado en el resumen.

## 25. Guía de integración para las pantallas del motorista

Esta guía aplica a `REPARTIDOR_CORPORATIVO` (Analiza) y `REPARTIDOR_RED`.
Los endpoints y ejemplos completos están en las secciones 19 a 24. La app
debe usar el host de su despliegue: Corporate y Network no comparten datos ni
sesiones.

| Pantalla o acción | API disponible | Dato o regla para la interfaz |
|---|---|---|
| Acceso e inicio | Autenticación local durante desarrollo; `GET /api/v1/usuarios/mi-perfil/`; `GET /api/v1/repartidores/mi-perfil/` | Usar `roles` y `permisos` para la navegación; consultar el perfil de motorista para obtener `id`, estado, capacidad y vehículo antes de iniciar jornada. |
| Jornada actual | `GET /api/v1/jornadas/activa/`; `POST /api/v1/jornadas/iniciar/` | `jornada: null` significa que aún no comenzó. El inicio devuelve `id` de jornada y `repartidor_id`; conservar ambos. |
| Servicios asignados | `GET /api/v1/solicitudes/`; `GET /api/v1/solicitudes/{solicitud_id}/` | El listado paginado se limita al motorista autenticado. Separar servicios en curso e históricos mediante `estado`; consultar el detalle antes de operar. |
| Recolección, traslado y entrega | `POST /api/v1/solicitudes/{solicitud_id}/transiciones/` | Mostrar solo la transición siguiente de la matriz de la sección 21; usar el detalle devuelto como estado actualizado. |
| Fotos | `POST /api/v1/solicitudes/{solicitud_id}/evidencias/`; `GET` de evidencias y archivo | Registrar `FOTO_RECOLECCION` en `AT_PICKUP` antes de `PICKED_UP`, y `FOTO_ENTREGA` en `AT_DESTINATION` antes de `DELIVERED`. El archivo requiere Bearer token. |
| Ubicación e incidencias | `POST /api/v1/seguimiento/registros/`; `POST /api/v1/incidencias/` | Enviar GPS con `jornada_id` e `id_cliente` estable; las incidencias pertenecen a una jornada activa. |
| Cierre y resumen | `POST /api/v1/jornadas/{jornada_id}/finalizar/`; `GET /api/v1/jornadas/` | No se puede cerrar con asignaciones activas. El resumen de jornada no ofrece kilómetros generales medidos. |

`GET /api/v1/solicitudes/` acepta `estado`, `prioridad` y `modalidad` como
filtros, pero solo un valor de `estado` por petición. Para una vista de
servicios en curso se pueden separar localmente los estados no terminales del
listado paginado, recorriendo todas sus páginas. Para el historial, los
estados terminales son `DELIVERED`, `CANCELLED`, `PICKUP_FAILED` y
`DELIVERY_FAILED`. Una solicitud reasignada deja de ser visible para el
motorista anterior; por ahora no existe un historial propio independiente de
las solicitudes visibles. Tampoco hay un endpoint de orden de paradas o
«siguiente servicio».

En Analiza, `modalidad` distingue `ENTRE_SUCURSALES`,
`EMPRESA_TRANSPORTE` y `ESPECIAL`. En las dos primeras, `origen` y `destino`
incluyen coordenadas registradas. `presentacion_ruta: "MAPA"` expresa la
presentación prevista, pero **no** significa que la respuesta ya incluya
polilínea, ruta calculada, distancia de Google, ETA ni redirección al tomar
otra calle. En `ESPECIAL`, `destino` es `null`, se muestra el texto
`destino_especial` y `presentacion_ruta: "SOLO_KILOMETROS"`: no debe dibujarse
una ruta seleccionada. Sus kilómetros GPS aparecen en
`kilometros_envio_especial` solo al cerrar el movimiento. Network mantiene su
operación abierta y no usa estas restricciones corporativas.

Para un envío `ESPECIAL`, antes de pasar a `PICKED_UP` debe existir jornada
activa, foto de recolección y coordenadas en la transición. Al finalizar o
fallar la entrega se requieren también las coordenadas finales y, para
`DELIVERED`, la foto de entrega. Enviar primero los puntos GPS pendientes:
el kilometraje especial se congela al cerrar y los puntos tardíos no lo
recalculan.

Ante una respuesta perdida, volver a consultar jornada y detalle de solicitud
antes de repetir una transición, cierre o carga de foto: esas operaciones no
tienen clave de idempotencia pública. La excepción son los registros GPS,
que sí admiten reenvío idéntico con el mismo `id_cliente`. Las notificaciones
persistentes se consultan por API; todavía no hay entrega push ni eventos en
tiempo real. Actualizar listados y detalles por consulta periódica o al volver
a la pantalla.

### Datos que todavía faltan para completar la interfaz del motorista

- No existe aún una API de ruta calculada, paradas ordenadas, ETA o recálculo
  con Google Maps. La pantalla «Mi ruta» puede mostrar la lista de servicios
  asignados y sus ubicaciones registradas; navegación y optimización de ruta
  quedan para la siguiente fase.
- No existe un resumen de kilómetros generales de jornada. Mostrar los
  kilómetros de `ESPECIAL` solo en ese envío terminado, nunca como total de
  jornada ni como distancia de todos los servicios.

## 26. Panel administrativo

El backend no expone Django Admin. El frontend debe construir el panel usando
estas API y los permisos recibidos en `mi-perfil`. Ocultar botones en la UI no
reemplaza las validaciones del backend.

## 27. Endpoints futuros

La recuperación de contraseña por correo está prevista para una fase posterior
y utilizará la API de Brevo cuando el proveedor sea `LOCAL`. No aplicará al
proveedor `JWT_CORPORATIVO`, cuya recuperación dependerá del sistema central.
Todavía no existe un endpoint disponible, no se ha instalado una dependencia
para Brevo y no se requieren credenciales de ese proveedor en la configuración
actual.

Cuando se implemente una API nueva deberá agregarse primero a la tabla de
endpoints, documentar su contrato completo y registrar el cambio en el
historial.

## 28. Lista de verificación para actualizar este documento

Por cada cambio de API:

1. Actualizar la fecha y el historial.
2. Actualizar la tabla general de endpoints.
3. Documentar método, ruta, modo y autenticación.
4. Documentar todos los campos y su obligatoriedad.
5. Añadir ejemplos JSON válidos.
6. Documentar códigos HTTP y reglas del frontend.
7. Marcar explícitamente cualquier cambio incompatible.
8. Confirmar que el comportamiento documentado tiene pruebas en el backend.

## 29. Datos locales de prueba para Corporate

En `vitago_corporativo` local existe un escenario ficticio de Analiza para
integración visual. No añade endpoints ni cambia ningún JSON:

- `GET /api/v1/solicitudes/opciones-creacion/` ofrece dos sucursales de origen;
  con `modalidad=ENTRE_SUCURSALES` y el origen «Prueba - Sucursal Centro»,
  devuelve «Prueba - Sucursal Norte» como destino. Con
  `modalidad=EMPRESA_TRANSPORTE`, devuelve «Prueba - Empresa de transporte».
- El comando de datos de prueba prepara, si aún faltan, una solicitud entre
  sucursales y otra hacia empresa de transporte. Las nuevas se asignan
  automáticamente si hay un motorista elegible; las creadas antes de este
  cambio pueden seguir `PENDING`. El listado real puede incluir más pruebas
  realizadas desde la app: no asumir una cantidad ni estado fijos.
- Los UUID y números de solicitud se generan en la base local; el frontend
  debe obtenerlos de la API y nunca fijarlos en el código.

Las coordenadas y direcciones del escenario son ficticias; no sirven para
probar rutas ni kilometraje de Google Maps. Si un usuario cambia el estado de
las solicitudes durante las pruebas, repetir el comando no las restablece.
La preparación y sus requisitos están descritos en
`VITAGO_EJECUCION_LOCAL.md`.

## 30. Notificaciones persistentes y validaciones

Estas rutas están disponibles en Corporate y Network, requieren Bearer token
y solo muestran o modifican notificaciones del usuario autenticado. La
asignación crea una notificación para el motorista nuevo; la reasignación
notifica también al anterior. Una solicitud `PRIORITY` produce para el nuevo
motorista una única notificación de tipo `SOLICITUD_PRIORITARIA` en lugar de
duplicar el aviso de asignación. Se guardan dentro de la misma transacción.

```http
GET /api/v1/notificaciones/?pagina=1&tamano_pagina=20
GET /api/v1/notificaciones/conteo-no-leidas/
POST /api/v1/notificaciones/{notificacion_id}/marcar-leida/
```

El listado responde `200` con el sobre paginado estándar, ordenado de la más
reciente a la más antigua:

```json
{
  "conteo": 1,
  "pagina_siguiente": null,
  "pagina_anterior": null,
  "resultados": [
    {
      "id": "92566b94-d543-4b61-bc17-bf63a8aa3b58",
      "tipo": "SOLICITUD_ASIGNADA",
      "titulo": "Nuevo servicio asignado",
      "mensaje": "Tienes asignada la solicitud SOL-001.",
      "solicitud_id": "c1901dbb-f48b-4ec7-836e-a69f9e47abca",
      "ruta": "/solicitudes/c1901dbb-f48b-4ec7-836e-a69f9e47abca",
      "enlace_profundo": "vitago-corporate:///solicitudes/c1901dbb-f48b-4ec7-836e-a69f9e47abca",
      "leida": false,
      "leida_en": null,
      "creado_en": "2026-10-01T12:00:00Z"
    }
  ]
}
```

En Network, `enlace_profundo` usa el esquema
`vitago-network:///solicitudes/{solicitud_id}`. `ruta` siempre es
`/solicitudes/{solicitud_id}`. Los tipos posibles son `SOLICITUD_ASIGNADA`,
`SOLICITUD_REASIGNADA`, `SOLICITUD_RETIRADA` y
`SOLICITUD_PRIORITARIA`. No implica que Android ya tenga registrado el
esquema; esa configuración corresponde a la app. Por ahora consultar el
conteo al abrir la pantalla o periódicamente; no existe push.

El conteo responde `200` con `{"conteo_no_leidas": 1}`. Marcar leída no
requiere cuerpo; responde `200` con el mismo objeto de notificación,
`leida: true` y `leida_en` con fecha. Repetir la operación es seguro. Una
notificación ajena o inexistente responde `404`.

Los errores de validación `400` mantienen claves de campo estables, por
ejemplo `correo`, `placa`, `empresa_id`, `sucursal_id`, `rol_codigo`,
`origen_id` y `destino_id`; los errores generales pueden usar `detail`.
Para artículos, cada error identifica explícitamente el índice cero-basado
y el campo:

```json
{
  "articulos": [
    {"indice": 1, "campo": "cantidad", "mensaje": "Debe ser positiva."}
  ]
}
```

Un `400` o `409` recibido con JSON es una respuesta del backend y no debe
mostrarse como error genérico de conexión.
