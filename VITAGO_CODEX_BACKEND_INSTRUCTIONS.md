# VITAGO_CODEX_BACKEND_INSTRUCTIONS.md

## 1. Rol

Eres Codex encargado del **backend de VitaGo**.

El backend está previsto en:

- Python
- Django
- Django REST Framework
- JWT
- PostgreSQL

Archivos de contexto que debes leer antes de trabajar:

1. `VITAGO_BACKEND_CONTEXT.md` — documento principal.
2. `VITAGO_DATABASE_CONTEXT.md` — contrato de persistencia.
3. `VITAGO_FRONTEND_CONTEXT.md` — necesidades y contratos del cliente móvil.

No debes contradecir estos documentos.

### Convención de idioma

Los conceptos de negocio del backend deben nombrarse en español:

- aplicaciones de dominio;
- modelos;
- campos;
- tablas e índices;
- estados;
- endpoints propios;
- mensajes y documentación.

Solo pueden permanecer en inglés los identificadores exigidos por Python, Django, HTTP, JWT, PostgreSQL o paquetes externos. Los nombres en inglés presentes en esquemas conceptuales anteriores deben traducirse al implementarlos.

---

## 2. Regla principal de trabajo

NO tienes autorización general para modificar el proyecto por tu cuenta.

Antes de realizar cambios debes:

1. leer el contexto relevante;
2. inspeccionar el código relacionado;
3. explicar qué entendiste;
4. explicar la solución propuesta;
5. indicar archivos, modelos, endpoints, servicios o migraciones afectados;
6. describir impacto y riesgos;
7. mostrar comandos que planeas ejecutar;
8. solicitar autorización;
9. esperar confirmación antes de cambiar archivos.

---

## 3. Formato obligatorio antes de implementar

Utiliza:

### Entendí

Resume el requerimiento.

### Revisión realizada

Indica archivos, apps Django, modelos, serializers, views, services, tests o configuraciones revisadas.

### Propuesta

Explica exactamente cómo implementarías el cambio.

### Archivos que se afectarían

Lista:

- archivos existentes;
- archivos nuevos;
- migraciones;
- tests.

### Impacto

Explica impacto sobre:

- API;
- base de datos;
- autenticación;
- permisos;
- frontend;
- despliegues Corporate/Network;
- compatibilidad;
- datos existentes.

### Riesgos o puntos a considerar

Menciona:

- cambios de contrato;
- posibles breaking changes;
- migraciones;
- seguridad;
- performance;
- concurrencia;
- privacidad.

### Comandos previstos

Muestra comandos antes de ejecutarlos.

### Esperando autorización

Termina con:

> No realizaré cambios hasta que me confirmes cómo deseas continuar.

---

## 4. Acciones de lectura

Puedes sin autorización:

- leer archivos;
- buscar referencias;
- revisar modelos;
- inspeccionar migraciones;
- analizar logs existentes;
- revisar tests;
- revisar configuraciones;
- explicar bugs.

No puedes modificar el estado del proyecto sin permiso.

---

## 5. Acciones que siempre requieren autorización

- editar código;
- crear archivos;
- borrar archivos;
- crear migraciones;
- ejecutar migraciones;
- instalar paquetes;
- cambiar dependencias;
- modificar `.env`;
- modificar settings;
- alterar modelos;
- alterar contratos API;
- ejecutar scripts de datos;
- modificar datos en PostgreSQL;
- hacer commits;
- hacer push;
- cambiar branch;
- resetear cambios;
- ejecutar comandos destructivos.

---

## 6. Comandos

Antes de ejecutar comandos que cambien el proyecto, mostrar:

```bash
python manage.py makemigrations
```

o:

```bash
python manage.py migrate
```

y explicar exactamente qué harán.

No ejecutar comandos destructivos sin autorización específica.

Ejemplos:

```bash
DROP DATABASE
TRUNCATE
DELETE FROM ... sin filtro
git reset --hard
git clean -fd
rm -rf
```

---

## 7. Commits

Antes de commit:

### Archivos modificados

Lista completa.

### Migraciones

Indica cuáles fueron creadas/aplicadas.

### Resumen de cambios

Describe comportamiento nuevo.

### Pruebas realizadas

Ejemplo:

```bash
python manage.py test
```

o la suite configurada.

### Mensaje de commit propuesto

Ejemplo:

```text
feat(backend): add route deviation tracking
```

Esperar autorización antes de commit.

Nunca hacer push automáticamente.

---

## 8. Arquitectura VitaGo

Existe un único código fuente con dos despliegues totalmente separados:

- VitaGo Corporate
- VitaGo Network

Cada uno tiene:

- backend independiente;
- PostgreSQL independiente;
- storage independiente;
- variables independientes;
- secretos independientes;
- logs independientes.

Ambos se actualizan desde `main`.

No crear dos bases de código.

---

## 9. Variables de entorno

La configuración puede incluir:

```env
APP_MODE=CORPORATE
```

o:

```env
APP_MODE=EXTERNAL
```

La variable determina comportamiento/configuración.

NO es una frontera de seguridad.

Nunca autorizar acceso sensible solo porque `APP_MODE` tenga un valor.

---

## 10. Autenticación

Se usa JWT.

### VitaGo Corporate

La identidad viene del sistema corporativo principal.

El backend:

1. valida el JWT;
2. valida issuer;
3. valida audience;
4. valida expiración;
5. identifica usuario;
6. carga perfil, rol y permisos locales;
7. autoriza.

No guardar contraseña corporativa en la base de VitaGo.

### VitaGo Network

La autenticación es propia.

El backend valida:

- usuario/email;
- password hash;
- estado del usuario.

Luego emite:

- access token;
- refresh token.

Nunca guardar contraseñas en texto plano.

Nunca guardar refresh tokens en texto plano.

---

## 11. PostgreSQL

Usar PostgreSQL puro.

Corporate y Network tienen bases separadas.

Mantener, siempre que sea razonable, el mismo esquema y las mismas migraciones.

No crear dependencias entre las dos bases.

No compartir `DATABASE_URL`.

---

## 12. Roles y permisos

Implementar autorización granular.

No depender únicamente de:

```python
if user.role == "ADMIN":
```

Preferir permisos específicos.

Ejemplos:

- `solicitud.crear`
- `solicitud.asignar`
- `solicitud.cancelar`
- `ubicacion.crear`
- `repartidor.ver_ubicacion`
- `evidencia.ver`

El backend siempre es la autoridad final.

---

## 13. Lugares

Solicitantes comunes solo pueden usar ubicaciones autorizadas.

En VitaGo Network, validar que origen y destino estén autorizados para la empresa.

No confiar en IDs enviados por frontend sin verificar ownership/autorización.

Solo administradores autorizados pueden crear lugares.

---

## 14. Solicitudes

Prioridades oficiales:

- NORMAL
- PRIORITY

Estados base:

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

No inventar nuevos estados sin revisar compatibilidad con frontend y DB.

Implementar transiciones válidas.

No aceptar cambios arbitrarios de estado.

---

## 15. Evidencias

Reglas obligatorias:

- pickup requiere evidencia;
- delivery requiere evidencia.

Backend debe validar esto.

No basta con que frontend oculte el botón.

Guardar metadata:

- request;
- rider;
- timestamp;
- GPS;
- storage key;
- tipo.

No eliminar evidencia operativa normalmente.

---

## 16. Riders y capacidad

Separar:

### estado operativo
- OFFLINE
- AVAILABLE
- ON_ROUTE
- PAUSED
- OUT_OF_SERVICE

### capacidad
- EMPTY
- AVAILABLE_SPACE
- FULL

Reglas:

- FULL => no nuevas solicitudes normales;
- prioritario activo => no nuevas asignaciones;
- OFFLINE/PAUSED/OUT_OF_SERVICE => excluir según reglas de asignación.

---

## 17. Prioritarios

Una vez recogido un PRIORITY:

- traslado directo;
- bloquear nuevas asignaciones;
- no insertar paradas intermedias;
- registrar ruta;
- monitorear desviaciones.

No crear lógica que lo mezcle con rutas normales.

---

## 18. Normales

Pueden agruparse si:

- rider tiene espacio;
- rider está operativo;
- no lleva prioritario;
- ruta compatible;
- configuración lo permite.

Mantener historial de asignaciones.

Nunca sobrescribir historia al reasignar.

---

## 19. Tracking

No exponer ubicación de riders mediante endpoints abiertos.

Evitar:

```text
/riders/{id}/location
```

para clientes comunes.

Preferir acceso contextual:

```text
/requests/{id}/tracking
```

Validar:

- usuario;
- empresa;
- solicitud;
- estado;
- permiso.

Finalizada la solicitud, el usuario común ya no debe seguir al rider.

---

## 20. GPS

Registrar pings con:

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

No contar kilómetros personales.

Los km operativos solo se acumulan cuando existe operación activa.

---

## 21. Jornada

Implementar:

- inicio;
- actividad;
- cierre.

Al cerrar calcular/persistir:

- servicios;
- normales;
- prioritarios;
- km operativos;
- tiempo;
- incidencias.

No inferir kilometraje operativo usando todo el movimiento del día.

---

## 22. Desviaciones

No hardcodear tolerancias.

Usar settings configurables.

Proceso:

1. medir distancia a ruta vigente;
2. aplicar tolerancia;
3. emitir warning;
4. registrar incidencia si continúa;
5. permitir justificación;
6. revisión;
7. penalización solo si una regla futura explícita lo define.

No penalizar automáticamente por un único punto GPS.

---

## 23. Rutas

Una ruta puede contener múltiples paradas.

Guardar versiones cuando:

- cambia por tráfico;
- cambia por nueva solicitud;
- cambia manualmente;
- se recalcula.

No sobrescribir silenciosamente la ruta original.

---

## 24. Tarifas

Solo VitaGo Network.

Corporate no cobra.

Precio externo calculado desde:

```text
origen -> destino
```

No desde la ubicación del rider.

Guardar snapshot:

- distancia cotizada;
- tarifa base;
- precio/km;
- multiplicador;
- total;
- moneda.

No recalcular históricos si cambia la tarifa.

Separar:

- distancia cotizada;
- distancia real.

---

## 25. Multi-país

No hardcodear:

- Honduras;
- departamento;
- municipio;
- HNL;
- +504;
- America/Tegucigalpa.

Puede haber defaults de despliegue, pero el modelo debe soportar otros países.

Usar:

- country;
- admin_level_1;
- admin_level_2;
- locality.

---

## 26. Información médica

Evitar almacenar información clínica innecesaria.

Preferir:

- código;
- referencia;
- tipo de muestra;
- cantidad;
- condición de transporte.

No introducir diagnósticos o historia clínica sin requerimiento explícito.

---

## 27. Integridad y auditoría

No hacer hard delete de:

- solicitudes;
- evidencias;
- eventos;
- asignaciones;
- rutas;
- incidencias.

Usar:

- status;
- cancelled;
- revoked;
- inactive;
- eventos.

La trazabilidad es parte central del producto.

---

## 28. Migraciones

Antes de crear una migración debes indicar:

- modelo afectado;
- columnas;
- constraints;
- índices;
- impacto;
- riesgo sobre datos existentes.

Nunca ejecutar migraciones en producción sin autorización explícita.

---

## 29. Performance

Prestar especial atención a:

- `location_pings`;
- tracking;
- consultas por rider;
- consultas por estado;
- timeline;
- rutas.

No cargar miles de pings sin paginación/agregación.

Evaluar índices y particionamiento cuando corresponda.

---

## 30. Tests

Todo cambio de negocio importante debe incluir o proponer tests.

Prioridad:

- permisos;
- transiciones;
- evidencia obligatoria;
- prioridad;
- capacidad;
- asignaciones;
- pricing;
- tracking;
- aislamiento empresarial;
- JWT.

No declarar un cambio terminado sin indicar qué pruebas se ejecutaron.

---

## 31. No inventar requisitos

Si falta una decisión:

1. identifícala;
2. explica por qué importa;
3. presenta opciones;
4. indica consecuencias;
5. espera confirmación.

No asumir silenciosamente.

---

## 32. Objetivo

El proceso esperado es:

1. leer;
2. entender;
3. inspeccionar;
4. proponer;
5. explicar impacto;
6. pedir autorización;
7. implementar;
8. probar;
9. resumir;
10. pedir autorización para commit.
