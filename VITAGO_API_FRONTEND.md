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

Última actualización: **2026-09-21**.

## 2. Historial de cambios

| Versión | Fecha | Cambio |
|---|---|---|
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

- Solicitudes y respuestas: `application/json`.
- Identificadores: UUID representados como texto.
- Fechas: ISO 8601 con zona horaria, normalmente UTC.
- Nombres controlados por VitaGo: español en `snake_case`.
- Autorización: `Authorization: Bearer <token>`.
- Una respuesta `204 No Content` no contiene JSON.

El frontend no debe calcular la vigencia de los tokens con duraciones
hardcodeadas. Debe usar `expira_token_acceso_en` y
`expira_token_refresco_en` recibidos del backend.

## 4. Modos de despliegue

El mismo backend se ejecuta en dos modos separados.

### CORPORATIVO

- La autenticación pertenece al sistema corporativo central.
- El frontend obtiene el JWT del proveedor corporativo.
- VitaGo recibe ese JWT mediante el encabezado `Bearer`.
- VitaGo no recibe ni almacena la contraseña corporativa.
- Los endpoints locales de inicio y renovación de sesión externa no están
  disponibles.

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
| `POST` | `/api/v1/autenticacion/iniciar-sesion/` | EXTERNO | Pública | `200` |
| `POST` | `/api/v1/autenticacion/renovar/` | EXTERNO | Refresh token en JSON | `200` |
| `POST` | `/api/v1/autenticacion/cerrar-sesion/` | EXTERNO | Access token | `204` |
| `POST` | `/api/v1/autenticacion/cerrar-todas-las-sesiones/` | EXTERNO | Access token | `204` |

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
| `404` | El endpoint no está disponible en el modo actual. |
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

Este endpoint no confirma por sí solo que PostgreSQL o servicios externos estén
disponibles.

## 8. Inicio de sesión externo

### `POST /api/v1/autenticacion/iniciar-sesion/`

Disponible únicamente en modo `EXTERNO`.

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

Disponible únicamente en modo `EXTERNO`.

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

Disponible únicamente en modo `EXTERNO`.

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
- `404`: endpoint no disponible en el modo actual después de autenticarse.

## 11. Cierre de todas las sesiones

### `POST /api/v1/autenticacion/cerrar-todas-las-sesiones/`

Disponible únicamente en modo `EXTERNO`.

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
- `404`: endpoint no disponible en el modo actual después de autenticarse.

## 12. Uso del JWT corporativo

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

## 13. Almacenamiento y manejo de tokens

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

## 14. Endpoints futuros

La recuperación de contraseña por correo está prevista para una fase posterior
y utilizará la API de Brevo. Todavía no existe un endpoint disponible, no se ha
instalado una dependencia para Brevo y no se requieren credenciales de ese
proveedor en la configuración actual.

Cuando se implemente una API nueva deberá agregarse primero a la tabla de
endpoints, documentar su contrato completo y registrar el cambio en el
historial.

## 15. Lista de verificación para actualizar este documento

Por cada cambio de API:

1. Actualizar la fecha y el historial.
2. Actualizar la tabla general de endpoints.
3. Documentar método, ruta, modo y autenticación.
4. Documentar todos los campos y su obligatoriedad.
5. Añadir ejemplos JSON válidos.
6. Documentar códigos HTTP y reglas del frontend.
7. Marcar explícitamente cualquier cambio incompatible.
8. Confirmar que el comportamiento documentado tiene pruebas en el backend.
