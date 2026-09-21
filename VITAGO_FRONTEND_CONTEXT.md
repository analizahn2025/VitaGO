# FRONTEND_CONTEXT.md

## 0. Identidad del producto

- Nombre del producto: **VitaGo**.
- App interna: **VitaGo Corporate**.
- App externa: **VitaGo Network**.
- Las dos apps salen del mismo proyecto móvil y cambian por flavor/configuración.


## 1. Objetivo

Crear una aplicación móvil VitaGo para logística y delivery del sector salud.

Se generarán dos aplicaciones/despliegues desde el mismo código fuente:

- Corporate
- External

Ambas comparten gran parte de la UI y lógica móvil, pero cambian mediante configuración/flavor/variables de entorno.

La app debe ser rápida, operativa y pensada para trabajo diario en calle.

---

## 2. Versiones

### Corporate

Uso interno de la empresa principal.

Características:

- login corporativo;
- riders propios;
- sucursales propias;
- sin precios;
- mantenimiento de flota;
- operación privada.

### External

Uso para empresas externas del sector salud.

Características:

- login propio;
- empresas externas;
- riders compartidos;
- tarifas por km;
- administración de lugares autorizados;
- tracking de solicitudes.

---

## 3. Configuración por build

Ejemplo conceptual:

```env
APP_MODE=CORPORATE
AUTH_MODE=CORPORATE_SSO
API_BASE_URL=https://corporate-api.example.com
FEATURE_PRICING=false
```

External:

```env
APP_MODE=EXTERNAL
AUTH_MODE=PLATFORM_AUTH
API_BASE_URL=https://external-api.example.com
FEATURE_PRICING=true
```

La app debe conocer su modo desde el inicio.

No esperar respuesta remota para saber si es Corporate o External.

---

## 4. Pantallas por rol

### Solicitante

- Inicio
- Nueva solicitud
- Mis solicitudes
- Detalle de solicitud
- Tracking en tiempo real
- Historial

### Rider

- Inicio
- Estado y capacidad
- Mi ruta
- Detalle de servicio
- Recolección
- Evidencia
- Entrega
- Incidencias
- Historial
- Jornada
- Resumen al finalizar jornada
- Mi vehículo si aplica

### Supervisor / Operador

- Dashboard
- Mapa de riders
- Solicitudes
- Asignaciones
- Detalle de rider
- Incidencias
- Rutas
- Reasignaciones

### Administrador

- Empresas
- Sucursales
- Usuarios
- Lugares
- Riders
- Vehículos
- Solicitudes
- Reportes
- Configuración

---

## 5. Flujo de nueva solicitud

El solicitante:

1. selecciona prioridad:
   - Normal
   - Prioritario
2. selecciona origen desde lista autorizada;
3. selecciona destino desde lista autorizada;
4. selecciona tipo de contenido;
5. agrega cantidad/referencia/observaciones;
6. revisa resumen;
7. confirma solicitud.

### Regla crítica

El usuario solicitante NO puede:

- escribir cualquier dirección;
- registrar un nuevo lugar;
- usar una ubicación aleatoria.

Solo administradores autorizados pueden registrar nuevos lugares.

---

## 6. Registro de lugares por administrador

Flujo:

1. buscar lugar con Google;
2. mostrar resultados;
3. seleccionar si existe;
4. si no aparece:
   - botón “¿No encuentras tu lugar?”
   - solicitar permiso GPS
   - obtener ubicación actual
   - mostrar mapa
   - permitir ajustar pin
   - completar datos
   - guardar
5. habilitar el lugar para la empresa.

Datos:

- nombre;
- tipo;
- dirección;
- teléfono;
- contacto;
- horario;
- instrucciones;
- coordenadas;
- Google Place ID si aplica.

---

## 7. Tipos de envío

### Normal

Puede agruparse con otros servicios.

El rider puede recibir nuevas asignaciones si:

- tiene espacio;
- no lleva prioritario;
- la lógica de ruta lo permite.

### Prioritario

Después de pickup:

- entrega directa;
- no puede recibir nuevas asignaciones;
- mostrar claramente que es exclusivo;
- destacar la ruta al destino;
- bloquear acciones incompatibles.

---

## 8. Inicio del rider

Mostrar:

- nombre;
- estado operativo;
- capacidad;
- servicios activos;
- siguiente parada;
- resumen de jornada.

Estados operativos:

- Disponible
- En ruta
- En pausa
- Fuera de servicio
- Desconectado

Capacidad:

- Vacío
- Con espacio
- Lleno

Capacidad debe ser fácil de cambiar.

---

## 9. Mi ruta

Mostrar lista ordenada de paradas.

Ejemplo:

```text
1. Clínica ABC
   Recolección
   Completado

2. Laboratorio Central
   Entrega
   Siguiente

3. Hospital X
   Recolección
   Pendiente
```

También mostrar mapa.

Si cambia la ruta por:
- nueva asignación normal;
- tráfico;
- cierre;
- recálculo;

la UI debe actualizarse.

---

## 10. Recolección

Pantalla debe mostrar:

- solicitud;
- origen;
- instrucciones;
- contenido esperado;
- referencia;
- botón de navegación;
- confirmar llegada;
- tomar fotografía;
- observaciones;
- confirmar recolección.

No permitir confirmar pickup sin evidencia requerida.

La evidencia debe incluir metadata del backend/GPS.

---

## 11. Entrega

Pantalla:

- destino;
- instrucciones;
- contenido;
- persona que recibe;
- fotografía;
- observaciones;
- confirmar entrega.

No permitir confirmar entrega sin fotografía.

Después de entregar, actualizar la solicitud inmediatamente.

---

## 12. Tracking para solicitante

Mientras la solicitud esté activa:

- mapa;
- rider;
- ubicación actual;
- estado;
- ETA si disponible.

Después de completar:

- dejar de mostrar tracking en tiempo real.

No exponer mapa general de riders al solicitante.

---

## 13. Control de ruta

El rider debe ver la ruta actual.

Cuando se detecte desviación:

### Advertencia

Mostrar mensaje claro:

> Te estás alejando de la ruta asignada.

No penalizar inmediatamente.

### Incidencia

Si la desviación supera parámetros configurados:

Mostrar selección de motivo:

- tráfico;
- calle cerrada;
- accidente;
- instrucción de supervisor;
- problema mecánico;
- emergencia;
- otro.

Enviar al backend.

Los umbrales vienen de configuración/API, no deben estar hardcodeados.

---

## 14. Jornada del rider

Debe existir:

- Iniciar jornada
- Finalizar jornada

Al finalizar mostrar resumen:

- servicios realizados;
- recolecciones;
- entregas;
- normales;
- prioritarios;
- km operativos;
- tiempo operativo;
- incidencias.

Regla:

No confundir km GPS total del dispositivo con km operativos.

---

## 15. Evidencias

Usar cámara.

Preferir captura directa en la app.

Evidencias mínimas:

- Pickup
- Delivery

Opcional:

- Incidencia

La UI debe impedir avanzar si falta evidencia obligatoria.

---

## 16. Empresas externas y precios

Solo External muestra tarifas.

Antes de confirmar solicitud, mostrar:

- distancia cotizada;
- tarifa;
- total;
- moneda.

Corporate nunca muestra precios.

No duplicar pantallas; usar configuración.

---

## 17. Login Corporate

La app Corporate inicia directamente con flujo corporativo.

No mostrar:

- registro libre;
- selección de tipo de empresa;
- login externo.

La app sabe desde build que es Corporate.

Después de autenticación:

- guardar token de forma segura;
- cargar perfil local;
- cargar roles/permisos;
- renderizar pantallas permitidas.

---

## 18. Login External

Pantallas:

- Login
- Recuperar acceso si se implementa
- Flujo de invitación/alta según reglas

El backend emite JWT.

Guardar tokens en almacenamiento seguro del dispositivo.

Nunca guardar contraseña.

---

## 19. Navegación por rol

La UI debe construirse según permisos.

No usar únicamente el nombre del rol.

Ejemplo:

Si el usuario tiene `request.assign`, mostrar asignación.

Si no tiene permiso, no mostrar la acción.

Aun así, el backend siempre valida.

---

## 20. Notificaciones

Preparar arquitectura para:

- nueva asignación;
- prioritario;
- reasignación;
- cambio de estado;
- incidencia;
- solicitud entregada;
- alerta de desviación;
- mantenimiento futuro si aplica.

---

## 21. Manejo offline / mala señal

Debe contemplarse desde diseño.

Prioridades:

- no perder evidencia;
- no perder cambios de estado;
- no perder eventos GPS críticos.

Posible estrategia:

- cola local;
- reintentos;
- timestamps;
- sincronización cuando vuelva internet.

No confirmar al usuario como “sincronizado” si el backend no respondió.

---

## 22. Privacidad

El solicitante solo ve tracking de sus solicitudes autorizadas.

El rider solo ve datos necesarios para ejecutar el servicio.

Evitar mostrar información clínica innecesaria.

Preferir códigos/referencias en lugar de diagnósticos o historial del paciente.

---

## 23. UI recomendada

La aplicación debe ser:

- clara;
- rápida;
- con botones grandes para uso en calle;
- con pocos pasos;
- legible bajo luz;
- sin sobrecargar con datos;
- orientada a acciones.

Para rider, priorizar:

- siguiente parada;
- navegación;
- evidencia;
- estado;
- capacidad;
- incidencias.

---

## 24. Reglas que Codex NO debe romper

1. Solicitante común no registra lugares.
2. Corporate no muestra tarifas.
3. External sí puede mostrar cotización.
4. Pickup requiere evidencia.
5. Delivery requiere evidencia.
6. Prioritario bloquea nuevas asignaciones.
7. Rider lleno no recibe servicios.
8. Tracking de cliente termina al cerrar su solicitud.
9. Kilómetros de jornada son solo operativos.
10. Umbrales de desviación son configurables.
11. Corporate y External salen del mismo código.
12. La app conoce su modo desde el build.
13. La UI nunca reemplaza la autorización del backend.
