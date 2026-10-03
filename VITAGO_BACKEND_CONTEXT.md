# BACKEND_CONTEXT.md

> Regla operativa vigente (2026-10-01): solo se crean y asignan motocicletas;
> los demás tipos permanecen únicamente por trazabilidad. La capacidad de
> carga en kg y la capacidad manual del motorista son obsoletas. El backend
> calcula `EMPTY`, `AVAILABLE_SPACE` y `FULL` con un máximo de cinco
> solicitudes activas (`ASSIGNED`, `GOING_TO_PICKUP`, `AT_PICKUP`,
> `PICKED_UP`, `IN_TRANSIT`, `AT_DESTINATION`). Las descripciones antiguas de
> capacidad manual o vehículos operativos de otros tipos quedan sustituidas
> por esta regla. Asignaciones y reasignaciones crean notificaciones
> persistentes por usuario.

> Flujo vigente desde 2026-10-01: crear una solicitud en Corporate intenta
> asignarla de inmediato al motorista elegible más cercano según el último
> punto GPS, con motoristas sin GPS al final. No hay aceptación ni rechazo:
> `AVAILABLE`/`ON_ROUTE`, cupo, prioridad, vehículo y alcance determinan la
> elegibilidad. Solo se notifica al elegido. Si no hay candidato, permanece
> `PENDING`. El selector entre sucursales puede devolver primero los orígenes
> sin exigir `origen_id` y, tras elegir origen, los destinos de la misma ciudad.

> Las solicitudes corporativas que quedan `PENDING` se reintentan tras el
> commit de creación y cuando un motorista pasa a disponible, inicia jornada,
> libera cupo al cerrar un servicio o queda libre por una reasignación. El
> reintento procesa hasta cinco pendientes por evento, en orden de antigüedad,
> reutilizando las mismas validaciones y notificación al motorista elegido.
> No requiere otro servidor ni modifica solicitudes de Network.

## 0. Identidad del producto

- Nombre del producto: **VitaGo**.
- Despliegue interno: **VitaGo Corporate**.
- Despliegue externo: **VitaGo Network**.
- Ambos salen del mismo código fuente y se diferencian por configuración/variables de entorno.

### Convención de idioma del backend

Los nombres controlados por VitaGo en el backend se escriben en español: aplicaciones, modelos, campos, tablas, estados, endpoints, mensajes y documentación. Solo se conservan en inglés los identificadores obligatorios de Python, Django, HTTP, JWT, PostgreSQL o dependencias externas.


## 1. Objetivo del proyecto

Construir el backend de una aplicación móvil VitaGo, especializada en logística y delivery para el sector salud.

El sistema tendrá **dos despliegues completamente separados**, pero ambos saldrán del **mismo código fuente** y de la misma rama principal (`main`):

- `CORPORATE`
- `EXTERNAL`

Cada despliegue tendrá su propio:
- frontend/app móvil;
- backend;
- base de datos PostgreSQL;
- almacenamiento de evidencias;
- configuración;
- secretos;
- dominio/API;
- logs y backups.

Las diferencias de comportamiento se controlarán principalmente mediante variables de entorno y configuración del despliegue.

Ejemplo:

```env
APP_MODE=CORPORATE
```

o:

```env
APP_MODE=EXTERNAL
```

No se deben mantener dos repositorios separados para Corporate y External.

---

## 2. Regla arquitectónica principal

El código debe ser compartido.

Cuando se actualice `main`, ambos productos deben poder desplegar la misma versión del software, utilizando configuraciones distintas.

Evitar llenar el código de condicionales dispersos como:

```python
if APP_MODE == "CORPORATE":
    ...
else:
    ...
```

Preferir servicios, módulos, estrategias o feature flags centralizados.

Ejemplo conceptual:

```text
pricing/
  corporate.py
  external.py

auth/
  corporate.py
  external.py
```

---

## 3. Modos de operación

### CORPORATE

Es la versión privada de la empresa principal.

Características:

- Tiene sus propios riders/deliverys.
- Tiene sus propias sucursales.
- Tiene sus propios usuarios.
- Tiene sus propios vehículos.
- Tiene sus propias solicitudes.
- Tiene sus propias evidencias.
- Tiene sus propias métricas.
- Tiene mantenimiento de flota.
- No utiliza tarifas por servicio.
- No comparte riders con empresas externas.
- Toda la información queda aislada en infraestructura Corporate.

### EXTERNAL

Es la versión para empresas externas del sector salud.

Características:

- Atiende clínicas, laboratorios, hospitales, consultorios, farmacias y otras empresas del sector salud.
- Las empresas externas generan solicitudes.
- Los riders de red son compartidos entre empresas externas.
- Sí existe tarifa por servicio.
- La tarifa se calcula usando la distancia de ruta entre origen y destino.
- Los solicitantes solo pueden seleccionar ubicaciones previamente aprobadas para su empresa.
- No pueden registrar destinos arbitrarios.

---

## 4. Autenticación

Se usará JWT.

PostgreSQL será la base de datos de aplicación.

### CORPORATE

La autenticación pertenece al sistema corporativo central.

El backend VitaGo Corporate:

1. recibe un JWT corporativo;
2. valida firma, expiración, issuer y audience;
3. identifica al usuario mediante un identificador corporativo;
4. carga su perfil, roles y permisos locales de Delivery;
5. autoriza la operación.

VitaGo Corporate NO debe almacenar contraseñas corporativas.

La tabla local de usuarios puede almacenar:

- `id`
- `external_auth_id`
- nombre
- apellido
- email
- empresa
- sucursal
- estado
- roles/permisos locales

### EXTERNAL

La autenticación es propia de VitaGo Network.

Flujo:

1. usuario envía email/usuario + contraseña;
2. backend valida contra `password_hash`;
3. si es válido, emite JWT;
4. se utiliza access token + refresh token.

Nunca almacenar contraseñas en texto plano.

Usar un algoritmo robusto de password hashing.

### Sesiones

Se recomienda una tabla `auth_sessions` o equivalente para:

- refresh tokens revocables;
- cierre de sesión remoto;
- múltiples dispositivos;
- revocar dispositivos perdidos;
- invalidar sesiones de usuarios desactivados.

Nunca almacenar refresh tokens en texto plano; almacenar hash.

Implementación vigente:

- `MODO_APLICACION` controla las reglas del producto y
  `PROVEEDOR_AUTENTICACION` controla la estrategia de identidad.
- `LOCAL` usa correo y contraseña, sesiones revocables, access token de 15
  minutos y refresh token de 7 días por defecto; ambos periodos son
  configurables.
- En desarrollo local, tanto `CORPORATIVO` como `EXTERNO` pueden utilizar el
  proveedor `LOCAL`. La configuración de producción rechaza expresamente
  `CORPORATIVO + LOCAL`.
- `JWT_CORPORATIVO` valida JWT RSA externos y exige firma, expiración, issuer,
  audience e identificador corporativo.
- VitaGo Network solo admite el proveedor `LOCAL`.
- Cada refresh token se rota y la sesión anterior queda revocada.
- La reutilización de un token revocado invalida la familia activa.
- Los access tokens contienen `usuario_id`, `sesion_id` y `familia`; su sesión
  se comprueba en cada solicitud para permitir revocación inmediata.
- Los refresh tokens se almacenan únicamente como HMAC-SHA256 con una clave
  independiente.
- Las contraseñas externas nuevas usan Argon2id.
- El cierre puede revocar una sesión o todas las sesiones activas del usuario.
- Las consultas de correo externo usan el valor normalizado exacto para
  aprovechar el índice único de PostgreSQL.
- Las respuestas bajo `/api/` informan el tiempo interno mediante
  `Server-Timing`; los registros de rendimiento no incluyen datos sensibles.
- El endpoint protegido `GET /api/v1/usuarios/mi-perfil/` expone la identidad
  local, el contexto de empresa/sucursal, los roles activos con su alcance y la
  unión ordenada de permisos activos. Funciona con la estrategia JWT del modo
  `CORPORATIVO` o `EXTERNO` y no reemplaza la autorización del backend.

---

## 5. Roles principales

El diseño debe soportar roles + permisos, no solo un único campo rígido.

Roles previstos:

- `SUPERADMINISTRADOR`
- `ADMINISTRADOR_CORPORATIVO`
- `GERENTE_OPERACIONES`
- `SOLICITANTE_CORPORATIVO`
- `ADMINISTRADOR_EMPRESA_EXTERNA`
- `SOLICITANTE_EXTERNO`
- `OPERADOR_RED`
- `REPARTIDOR_CORPORATIVO`
- `REPARTIDOR_RED`

Los nombres exactos pueden ajustarse, pero la autorización debe ser granular.

Ejemplos de permisos:

- `solicitud.crear`
- `solicitud.ver`
- `solicitud.asignar`
- `solicitud.reasignar`
- `solicitud.cancelar`
- `ubicacion.crear`
- `ubicacion.aprobar`
- `ubicacion.ver`
- `repartidor.ver_ubicacion`
- `repartidor.administrar`
- `vehiculo.administrar`
- `evidencia.ver`
- `reporte.ver`
- `empresa.administrar`
- `sucursal.administrar`

Autenticación y autorización son conceptos diferentes.

Alcances permitidos inicialmente:

- `SUPERADMINISTRADOR`: global.
- `ADMINISTRADOR_CORPORATIVO`: global o empresa.
- `GERENTE_OPERACIONES`: empresa.
- `SOLICITANTE_CORPORATIVO`: empresa o sucursal.
- `ADMINISTRADOR_EMPRESA_EXTERNA`: empresa.
- `SOLICITANTE_EXTERNO`: empresa o sucursal.
- `OPERADOR_RED`: global.
- `REPARTIDOR_CORPORATIVO`: empresa.
- `REPARTIDOR_RED`: global.

El catálogo y la matriz inicial se mantienen mediante una migración de datos. Tener un rol no permite salir del alcance asignado.

Implementación vigente de consulta organizacional:

- las empresas requieren `empresa.ver`;
- las sucursales requieren `sucursal.ver`;
- los listados respetan alcances `GLOBAL`, `EMPRESA` y `SUCURSAL`;
- los recursos existentes fuera del alcance responden como no encontrados;
- las listas se paginan con `pagina` y `tamano_pagina`;
- `POST /api/v1/organizaciones/empresas/{empresa_id}/sucursales/` permite a un
  administrador crear una sucursal únicamente con una ubicación activa y
  aprobada para la misma empresa.

---

## 6. Usuarios y acceso a datos

Implementación administrativa vigente:

- `GET /api/v1/usuarios/` lista únicamente usuarios visibles mediante
  `usuario.ver` y el alcance activo;
- `POST /api/v1/usuarios/` exige `usuario.administrar` y `rol.asignar` en el
  alcance solicitado;
- el backend impide asignar roles de otro modo de despliegue y utiliza una
  matriz explícita de delegación para evitar la creación de superadministradores
  o roles fuera de la autoridad del administrador;
- usuario y primer rol se crean dentro de una sola transacción;
- con autenticación `LOCAL` se exige una contraseña temporal validada y
  protegida mediante el hasher configurado;
- con `JWT_CORPORATIVO` se prohíbe la contraseña local y se exige el
  identificador del proveedor corporativo;
- `GET /api/v1/usuarios/{usuario_id}/` permite consultar el detalle solamente
  dentro de un alcance autorizado por `usuario.ver`;
- `PATCH /api/v1/usuarios/{usuario_id}/` permite modificar nombres, apellidos,
  teléfono y estado con `usuario.administrar`; no permite cambiar correo,
  organización ni roles;
- los cambios a `INACTIVO` o `SUSPENDIDO` revocan inmediatamente todas las
  sesiones con el motivo `USUARIO_INACTIVO`, y un administrador no puede
  aplicarse esos estados a sí mismo;
- el proveedor `LOCAL` admite el restablecimiento administrativo de contraseña
  en `POST /api/v1/usuarios/{usuario_id}/restablecer-contrasena/`; la nueva
  contraseña se valida, se almacena con hash y el cambio revoca todas las
  sesiones existentes;
- el restablecimiento local responde `404` con `JWT_CORPORATIVO`, porque la
  identidad y la contraseña pertenecen al sistema corporativo central;
- los usuarios no se eliminan físicamente: se desactivan para conservar la
  trazabilidad;
- `GET /api/v1/usuarios/{usuario_id}/roles/` devuelve el historial visible de
  asignaciones activas y revocadas según `usuario.ver` y alcance;
- `POST /api/v1/usuarios/{usuario_id}/roles/` permite conceder roles con
  `usuario.administrar` y `rol.asignar`, reutilizando la matriz de delegación,
  compatibilidad por despliegue y validación de alcance;
- `DELETE /api/v1/usuarios/{usuario_id}/roles/{asignacion_id}/` revoca sin
  borrar, registra autor y fecha, y cierra las sesiones locales del usuario;
- las revocaciones administrativas se serializan en PostgreSQL y se impiden
  cuando quitarían el último rol administrativo propio o dejarían un alcance
  sin otro administrador;
- una asignación revocada nunca se sobrescribe: una concesión posterior crea
  un nuevo registro para mantener el historial;
- no existe registro público de usuarios.

### Solicitante corporativo

Puede:
- crear solicitudes;
- ver las solicitudes permitidas por su sucursal/alcance;
- ver estado;
- ver rider asignado;
- ver mapa en tiempo real mientras su solicitud esté activa;
- ver evidencias permitidas.

No puede:
- registrar ubicaciones nuevas;
- ver riders ajenos;
- cambiar reglas operativas.

### Administrador de empresa externa

Puede:
- administrar usuarios de su empresa;
- administrar sucursales;
- registrar ubicaciones;
- aprobar lugares de uso;
- crear solicitudes;
- ver solicitudes de su empresa;
- ver tracking de sus solicitudes;
- consultar evidencias e historial.

### Solicitante externo

Puede:
- seleccionar únicamente ubicaciones autorizadas;
- crear solicitudes;
- ver sus solicitudes;
- ver tracking del rider mientras la solicitud esté activa.

No puede:
- registrar ubicaciones nuevas;
- escribir destinos arbitrarios;
- consultar datos de otras empresas.

### Rider

Puede:
- ver servicios asignados;
- ver ruta;
- confirmar llegada;
- tomar evidencia;
- confirmar recolección;
- confirmar entrega;
- cambiar capacidad;
- reportar incidencias;
- finalizar jornada.

No puede:
- reasignarse servicios arbitrariamente;
- eliminar evidencias;
- editar historial operativo.

---

## 7. Ubicaciones

Las ubicaciones deben salir de dos fuentes:

- Google Places / Google Maps.
- Registro propio de la plataforma.

Al registrar empresa o sucursal:

1. administrador busca el lugar en Google;
2. si aparece, se selecciona;
3. se guarda referencia del lugar y coordenadas;
4. si no aparece, mostrar “¿No encuentras tu lugar?”;
5. permitir registrar nueva ubicación;
6. solicitar ubicación GPS actual;
7. mostrar mapa para confirmar/ajustar pin;
8. completar datos;
9. guardar como ubicación propia.

Datos recomendados:

- nombre;
- tipo de lugar;
- Google Place ID si aplica;
- país;
- departamento;
- municipio;
- ciudad;
- colonia;
- dirección;
- latitud;
- longitud;
- teléfono;
- contacto;
- horario;
- referencias;
- instrucciones para delivery;
- estado;
- verificación.

El solicitante común NO registra lugares.

Debe existir una relación de lugares autorizados por empresa.

Implementación vigente:

- existe un catálogo de 13 tipos de ubicación mantenido mediante migraciones
  de datos;
- `GET /api/v1/ubicaciones/tipos/` devuelve únicamente tipos activos;
- la consulta requiere `ubicacion.ver` en cualquier alcance vigente;
- la migración se aplica de forma independiente en Corporate y Network;
- `GET` y `POST /api/v1/ubicaciones/` permiten consultar por empresa y registrar
  lugares con autorización granular;
- el registro crea de forma atómica la ubicación y su relación empresarial;
- `ubicacion.aprobar` controla el estado y los usos como origen o destino;
- el contrato HTTP utiliza `departamento`, `municipio`, `ciudad` y `colonia`;
  internamente los tres primeros se mapean a niveles administrativos genéricos
  para conservar compatibilidad multi-país y con Google Maps;
- se admite conservar un Google Place ID, pero todavía no existen llamadas
  activas a Google Maps.

---

## 8. Tipos de lugar

Ejemplos:

- hospital;
- clínica;
- laboratorio clínico;
- consultorio;
- farmacia;
- banco de sangre;
- centro de imágenes;
- centro médico;
- sucursal;
- residencia;
- empresa;
- otro.

El catálogo debe ser configurable.

---

## 9. Solicitudes

Cada solicitud debe tener:

- identificador UUID;
- número legible;
- empresa;
- sucursal solicitante;
- usuario solicitante;
- origen;
- destino;
- prioridad;
- tipo de servicio;
- estado;
- rider asignado;
- contenido/artículos;
- timestamps relevantes;
- observaciones;
- historial de eventos.

### Prioridades

Solo dos inicialmente:

- `NORMAL`
- `PRIORITY`

### Estados sugeridos

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

El backend debe ser la autoridad del cambio de estados.

No permitir transiciones inválidas.

Implementación vigente de la primera fase:

- existe la aplicación `solicitudes` con modelos para tipos de servicio,
  solicitudes, artículos y eventos;
- el catálogo inicial contiene nueve tipos con códigos de negocio en español;
- `GET /api/v1/solicitudes/tipos-servicio/` expone tipos activos;
- `GET /api/v1/solicitudes/` y
  `GET /api/v1/solicitudes/{solicitud_id}/` aplican visibilidad por permiso y
  alcance;
- `GET /api/v1/solicitudes/opciones-creacion/` centraliza las modalidades y
  los orígenes/destinos válidos, filtrando sucursales por empresa, alcance y
  ciudad, empresas de transporte aprobadas y la autorización especial;
- `GET /api/v1/solicitudes/resumen-solicitante/` agrega conteos por categoría
  y devuelve las cinco solicitudes visibles más recientes;
- `solicitud.ver_propias` limita solicitantes a filas creadas por ellos y
  `solicitud.ver_asignadas` limita motoristas a solicitudes actualmente
  asignadas a su perfil;
- `POST /api/v1/solicitudes/` crea en Corporate una solicitud `PENDING`, sus
  artículos y el evento `CREADA` dentro de una sola transacción;
- origen y destino deben estar activos, aprobados y habilitados para el uso
  correspondiente dentro de la misma empresa;
- la creación en Network responde `409` hasta que el backend pueda calcular y
  congelar la cotización de ruta y tarifa;
- `POST /api/v1/solicitudes/{solicitud_id}/asignaciones/` implementa la
  asignación y reasignación manual mediante permisos separados;
- la operación conserva todas las asignaciones anteriores, genera eventos y
  bloquea las filas involucradas dentro de una transacción;
- la asignación cambia `PENDING` a `ASSIGNED`;
- `POST /api/v1/solicitudes/{solicitud_id}/transiciones/` valida una matriz
  cerrada de transiciones y solo permite la operación al motorista asignado;
- la cancelación exige `solicitud.cancelar` y solo se admite antes de la
  recolección;
- los estados terminales cierran la asignación activa y liberan al motorista
  cuando no conserva otras asignaciones;
- cada transición registra un evento con responsable, motorista y GPS cuando
  fue proporcionado.

Reglas corporativas exclusivas de Analiza:

- `modalidad` es obligatoria al crear y admite `ENTRE_SUCURSALES`,
  `EMPRESA_TRANSPORTE` o `ESPECIAL`; `ABIERTO` queda reservado para Network;
- todo origen corporativo es una sucursal activa de la misma empresa;
- `ENTRE_SUCURSALES` exige otra sucursal activa de la misma empresa y ciudad;
- `EMPRESA_TRANSPORTE` exige una ubicación aprobada del tipo de catálogo
  `EMPRESA_TRANSPORTE`;
- `ESPECIAL` no usa destino registrado: conserva `destino_especial` como texto
  y la API ordena al frontend usar `presentacion_ruta=SOLO_KILOMETROS`;
- solo `GERENTE_OPERACIONES`, con alcance `EMPRESA` y el permiso adicional
  `solicitud.crear_envio_especial`, puede crear especiales. Un superusuario
  técnico mantiene el bypass administrativo de permisos;
- `GERENTE_OPERACIONES` integra la antigua supervisión corporativa y también
  posee `usuario.administrar` y `rol.asignar`; puede crear y administrar
  usuarios operativos y delegar solamente `SOLICITANTE_CORPORATIVO` y
  `REPARTIDOR_CORPORATIVO` dentro de su empresa;
- crear administradores, crear otros gerentes, administrar empresas,
  sucursales, aprobaciones de ubicaciones y configuración general continúa
  reservado a los administradores;
- un gerente tampoco puede modificar, suspender, restablecer credenciales ni
  revocar roles de administradores u otros gerentes;
- `SUPERVISOR_CORPORATIVO` permanece inactivo solo como referencia histórica y
  no puede asignarse;
- al pasar un especial a `PICKED_UP` se abre un movimiento GPS desde las
  coordenadas enviadas, se exige jornada activa y el motorista queda exclusivo
  con capacidad llena;
- `DELIVERED` o `DELIVERY_FAILED` cierran el movimiento con coordenadas,
  asocian los puntos recibidos, filtran mala precisión o velocidad imposible y
  congelan los kilómetros reales estimados;
- los umbrales se configuran con `PRECISION_GPS_MAXIMA_METROS` y
  `VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO`;
- este cálculo no utiliza Google Maps y no modifica las reglas abiertas de
  VitaGo Network.

---

## 10. Envíos prioritarios

Regla obligatoria:

Un servicio prioritario/urgente, una vez recolectado, debe ir directamente al destino.

Durante ese periodo:

- el rider queda bloqueado para nuevas asignaciones;
- no se deben insertar otras recolecciones;
- no se deben insertar otras entregas;
- el sistema debe tratarlo como servicio exclusivo;
- las desviaciones deben vigilarse con mayor atención.

Corporate no cobra por prioridad.

External podrá usar una regla tarifaria configurable si el negocio lo decide.

---

## 11. Envíos normales

Los normales pueden agruparse.

Un rider puede tener varias recolecciones y entregas activas si:

- no lleva prioritario;
- tiene capacidad disponible;
- está activo;
- la nueva solicitud es compatible con su ruta;
- las reglas operativas lo permiten.

La ruta puede contener secuencias como:

1. Pickup A
2. Pickup B
3. Delivery A
4. Pickup C
5. Delivery B
6. Delivery C

---

## 12. Capacidad del rider

Separar estado operativo de capacidad.

### Estado operativo

- `OFFLINE`
- `AVAILABLE`
- `ON_ROUTE`
- `PAUSED`
- `OUT_OF_SERVICE`

### Capacidad

- `EMPTY`
- `AVAILABLE_SPACE`
- `FULL`

Regla:

Si `capacity_status = FULL`, el rider no debe recibir nuevas solicitudes normales.

Si lleva prioritario, tampoco recibe nuevas solicitudes aunque tenga espacio.

La capacidad puede ser manual, porque el volumen físico real no siempre coincide con la cantidad de servicios.

Implementación vigente:

- `Repartidor` relaciona un usuario con su empresa, vehículo, estado operativo
  y capacidad;
- el nombre de negocio mostrado es motorista, pero se conservan los códigos
  técnicos `REPARTIDOR_CORPORATIVO` y `REPARTIDOR_RED`;
- cada cambio efectivo crea un `HistorialEstadoRepartidor`;
- solo aparecen como disponibles los perfiles activos con usuario activo,
  vehículo activo, estado `AVAILABLE` y capacidad distinta de `FULL`;
- Corporate exige alcance de empresa y Network usa motoristas globales;
- si un motorista ya transporta una solicitud prioritaria, se rechazan nuevas
  asignaciones.

---

## 13. Evidencias

La evidencia fotográfica es obligatoria en:

- recolección;
- entrega.

Reglas:

- no permitir `PICKED_UP` sin evidencia de pickup;
- no permitir `DELIVERED` sin evidencia de entrega;
- guardar fecha;
- hora;
- GPS;
- rider;
- solicitud;
- archivo;
- tipo de evidencia.

Preferir captura directa desde cámara.

Evitar depender únicamente de archivos seleccionados desde galería.

Tipos iniciales:

- `PICKUP_PHOTO`
- `DELIVERY_PHOTO`
- `INCIDENT_PHOTO`

Las evidencias no deben eliminarse como parte de la operación normal.

Implementación vigente:

- `EvidenciaSolicitud` conserva solicitud, motorista, tipo, clave privada de
  almacenamiento, tipo de contenido, tamaño, fecha de captura, GPS y notas;
- los tipos implementados son `FOTO_RECOLECCION`, `FOTO_ENTREGA` y
  `FOTO_INCIDENCIA`;
- `POST /api/v1/solicitudes/{solicitud_id}/evidencias/` recibe una imagen por
  `multipart/form-data` y solo permite registrarla al motorista asignado con
  `evidencia.crear`;
- JPEG, PNG y WebP se validan por tipo declarado, firma básica y tamaño máximo
  configurable;
- `PICKED_UP` exige evidencia de recolección y `DELIVERED` exige evidencia de
  entrega en el backend;
- el listado y la descarga requieren visibilidad contextual de la solicitud y
  `evidencia.ver`;
- los archivos se sirven mediante un endpoint autenticado, sin publicar la
  clave de almacenamiento;
- en desarrollo, cada modo usa por defecto una raíz local separada. El storage
  puede reemplazarse por despliegue sin cambiar el contrato HTTP.

---

## 14. Tracking en tiempo real

El usuario que solicitó el servicio puede ver el rider en tiempo real mientras la solicitud esté activa.

Regla de privacidad:

El cliente no debe poder seguir al rider después de finalizar la solicitud.

No exponer endpoints genéricos que permitan seguir cualquier rider.

Preferir:

```text
GET /requests/{request_id}/tracking
```

El backend valida que el usuario tenga acceso a esa solicitud.

Para supervisores y administradores puede existir un alcance diferente.

Tecnología posible:

- WebSockets;
- SSE;
- mecanismo realtime equivalente.

La elección final queda para implementación.

---

## 15. GPS y kilometraje operativo

El sistema debe recibir pings GPS durante servicios activos.

Datos recomendados:

- rider;
- shift;
- route;
- latitud;
- longitud;
- accuracy;
- speed;
- heading;
- timestamp;
- `is_operational`.

Regla fundamental:

Los kilómetros del resumen de jornada solo cuentan mientras exista operación activa.

Si el rider se mueve sin una recolección/servicio activo, esos kilómetros no cuentan como kilometraje operativo.

Cuando tiene una ruta activa con uno o más servicios, se registra kilometraje operativo.

Cuando termina el último servicio, se detiene el conteo operacional.

---

## 16. Jornada del rider

Debe existir:

- iniciar jornada;
- trabajar;
- finalizar jornada.

Al finalizar, mostrar:

- servicios realizados;
- recolecciones;
- entregas;
- normales;
- prioritarios;
- kilómetros operativos;
- tiempo operativo;
- incidencias;
- métricas del día.

El backend debe persistir un resumen de jornada.

Implementación vigente:

- `JornadaRepartidor` conserva inicio, cierre, GPS inicial/final, estado y el
  resumen operativo congelado;
- una restricción parcial permite una sola jornada `ACTIVA` por motorista;
- `POST /api/v1/jornadas/iniciar/` exige perfil, usuario y vehículo activos,
  además de `jornada.iniciar`, y cambia al motorista a `AVAILABLE`;
- `GET /api/v1/jornadas/activa/` permite recuperar el estado de la jornada
  propia sin convertir la ausencia en error;
- el listado y detalle aplican `jornada.ver`; un motorista solo ve sus propios
  registros, mientras los encargados usan alcance administrativo;
- el cierre exige `jornada.finalizar`, pertenencia de la jornada y ausencia de
  asignaciones activas;
- al cerrar se persisten servicios completados, recolecciones, entregas,
  normales, prioritarios y minutos activos, y el motorista queda `OFFLINE` con
  capacidad `EMPTY`;
- las incidencias reportadas durante la jornada ya se contabilizan en el
  resumen y se marcan como disponibles;
- los kilómetros permanecen marcados como no disponibles hasta implementar
  sus reglas de cálculo, evitando presentar ceros como una métrica real.

---

## 17. Control de ruta y desviaciones

No penalizar por pequeñas desviaciones de GPS.

Usar:

- corredor alrededor de la ruta;
- distancia fuera de ruta;
- tiempo fuera de ruta;
- recálculo de ruta;
- motivo de desviación;
- revisión administrativa.

Parámetros configurables, NO hardcodeados.

Ejemplo inicial NO definitivo:

```text
ROUTE_WARNING_DISTANCE_M
ROUTE_WARNING_SECONDS
ROUTE_INCIDENT_DISTANCE_M
ROUTE_INCIDENT_SECONDS
```

La lógica recomendada:

1. calcular distancia del rider a la polilínea de ruta vigente;
2. ignorar pequeñas fluctuaciones;
3. si supera umbral de advertencia durante cierto tiempo, avisar al rider;
4. si supera umbral de incidencia durante cierto tiempo, registrar desviación;
5. notificar al supervisor si corresponde;
6. permitir motivo:
   - tráfico;
   - calle cerrada;
   - accidente;
   - instrucción supervisor;
   - problema mecánico;
   - emergencia;
   - otro;
7. la penalización no debe ser automática por defecto;
8. registrar para revisión.

Si Google o el motor de rutas recalcula legítimamente la ruta, la nueva ruta debe convertirse en la ruta vigente.

En servicios normales, agregar una nueva parada válida debe generar nueva versión de ruta.

---

## 18. Tarifas - solo External

Corporate no utiliza precios.

External sí.

La tarifa debe calcularse usando la distancia de ruta entre:

```text
ORIGEN -> DESTINO
```

No desde la ubicación actual del rider hasta el origen.

Guardar:

- distancia cotizada;
- tarifa base;
- precio por km;
- mínimo;
- multiplicador de prioridad si aplica;
- subtotal;
- total;
- moneda;
- timestamp.

El precio debe quedar congelado al crear/confirmar la solicitud.

Un cambio futuro en tarifas no debe modificar solicitudes históricas.

Guardar por separado:

- `quoted_distance_km`
- `actual_distance_km`

La factura usa la distancia cotizada según las reglas de negocio.

---

## 19. Vehículos y mantenimiento

No limitar el modelo a motocicletas.

Usar entidad `vehicle`.

Puede representar:

- motocicleta;
- carro;
- panel;
- vehículo especial;
- otros.

Guardar:

- placa;
- marca;
- modelo;
- año;
- tipo;
- estado;
- kilometraje.

Mantenimiento:

- tipo;
- fecha;
- km al mantenimiento;
- próximo km;
- próxima fecha;
- costo;
- notas.

Principalmente relevante para Corporate.

Implementación vigente de flota básica:

- la aplicación `flota` persiste vehículos con placa única, empresa opcional,
  tipo, marca, modelo, año, capacidad de carga, estado y notas;
- Corporate exige empresa y Network utiliza vehículos de alcance global;
- los tipos implementados son `MOTOCICLETA`, `AUTOMOVIL`, `PANEL`, `ESPECIAL`
  y `OTRO`;
- los estados implementados son `ACTIVO`, `MANTENIMIENTO`, `FUERA_SERVICIO` e
  `INACTIVO`;
- el mantenimiento y kilometraje se mantienen como fase posterior.

---

## 20. Auditoría

Todo evento importante debe quedar trazable.

Ejemplos:

- creación solicitud;
- asignación;
- reasignación;
- cambio de estado;
- pickup;
- entrega;
- cancelación;
- evidencia;
- desviación;
- cambio de capacidad;
- inicio/fin de jornada.

No borrar historial para “corregir” operaciones.

Preferir eventos, anulaciones o estados.

---

## 21. Multi-país

La arquitectura debe quedar preparada.

No hardcodear “departamento/municipio”.

Guardar conceptos genéricos:

- country;
- admin_level_1;
- admin_level_2;
- locality.

Configuraciones por país:

- código telefónico;
- moneda;
- zona horaria;
- formatos;
- unidades;
- reglas futuras.

---

## 22. Integración con Google Maps

Se prevé usar servicios de Google para:

- Places Autocomplete;
- búsqueda de lugares;
- Place ID;
- geocodificación;
- rutas;
- distancia;
- duración estimada;
- navegación;
- polilíneas;
- recálculo de rutas.

No asumir que Google contiene toda la información logística.

La plataforma debe conservar su propia metadata:

- instrucciones de entrega;
- contacto;
- punto exacto de recepción;
- horarios;
- referencias internas.

---

## 23. Despliegue y CI/CD

Un mismo `main`.

Pipeline conceptual:

```text
PR / merge
   ↓
tests
   ↓
build
   ↓
deploy Corporate
   ↓
health check
   ↓
deploy External
```

Ambos usan la misma versión del código, con variables distintas.

Infraestructura aislada.

---

## 24. Variables de entorno sugeridas

```env
APP_MODE=CORPORATE|EXTERNAL
APP_NAME=
ENVIRONMENT=
DATABASE_URL=
JWT_ISSUER=
JWT_AUDIENCE=
JWT_PUBLIC_KEY=
JWT_PRIVATE_KEY=
AUTH_MODE=
STORAGE_BUCKET=
GOOGLE_MAPS_API_KEY=
DEFAULT_COUNTRY=
DEFAULT_TIMEZONE=
FEATURE_PRICING=
FEATURE_SHARED_RIDERS=
FEATURE_FLEET_MAINTENANCE=
```

No guardar secretos en el repositorio.

---

## 25. Reglas que Codex NO debe romper

1. No mezclar datos Corporate y External.
2. No almacenar contraseñas corporativas en VitaGo.
3. No permitir destinos arbitrarios a solicitantes comunes.
4. No permitir entregar sin evidencia.
5. No permitir pickup sin evidencia.
6. No asignar nuevos servicios a un rider lleno.
7. No asignar servicios adicionales durante un prioritario activo.
8. No contar kilómetros personales como operativos.
9. No permitir tracking de riders fuera del contexto autorizado.
10. No hardcodear tolerancias de ruta ni tarifas.
11. No mantener dos bases de código.
12. No eliminar trazabilidad operativa.
13. No confiar en `APP_MODE` como mecanismo de seguridad.
14. Toda autorización sensible debe validarse en backend.

---

## 26. Implementación vigente de seguimiento GPS

- La aplicación `seguimiento` recibe lotes de hasta 200 puntos GPS mediante
  `POST /api/v1/seguimiento/registros/`.
- Cada punto posee un `id_cliente` UUID y la combinación con el motorista es
  única, lo cual permite reintentos idempotentes cuando falla la red móvil.
- Solo el motorista propietario puede registrar puntos dentro del intervalo de
  una jornada propia y con el permiso `repartidor.registrar_ubicacion`.
- El backend determina `es_operativo` usando los intervalos entre
  `aceptada_en` y `finalizada_en` de las asignaciones; el frontend no controla
  esa clasificación.
- `GET /api/v1/solicitudes/{solicitud_id}/seguimiento/` exige visibilidad de la
  solicitud y `solicitud.ver_seguimiento` dentro del alcance organizacional.
- Una solicitud terminal nunca expone la ubicación actual del motorista.
- No existe un endpoint general para consultar la ubicación de un motorista.
- Esta fase usa consultas HTTP y no depende de Google Maps, Redis ni
  WebSockets.
- La acumulación de kilómetros permanece deshabilitada hasta establecer reglas
  para descartar baja precisión, saltos y velocidades anómalas.

---

## 27. Implementación vigente de incidencias operativas

- La aplicación `incidencias` permite que un motorista reporte una incidencia
  durante una jornada propia activa mediante `POST /api/v1/incidencias/`.
- La incidencia puede vincularse opcionalmente con una solicitud, pero solo si
  esa solicitud estaba asignada al mismo motorista al momento reportado.
- El motorista solo consulta sus propias incidencias. Los usuarios con
  `incidencia.revisar` consultan y revisan las incidencias dentro de su alcance
  administrativo o global.
- Los estados son `ABIERTA`, `EN_REVISION` y `CERRADA`. Solo se permiten las
  transiciones `ABIERTA -> EN_REVISION`, `ABIERTA -> CERRADA` y
  `EN_REVISION -> CERRADA`; una incidencia cerrada no se reabre.
- Cada alta y cambio de estado crea un `EventoIncidencia` inmutable para
  auditoría.
- El motorista propietario puede adjuntar imágenes mientras la incidencia no
  esté cerrada. Los archivos se guardan con clave privada y solo se descargan
  mediante endpoints autenticados y autorizados.
- No existe una operación HTTP de borrado para incidencias, eventos ni
  evidencias.
- El resumen de jornada cuenta las incidencias vinculadas con ella y publica
  `incidencias_disponibles=true`. El kilometraje continúa pendiente.
