# VitaGo con Docker

## Configuración simplificada

Solo hay dos Compose independientes:

- `docker-compose.yml`: Corporate, Network y PostgreSQL local de Network.
- `docker-compose.test.yml`: pruebas con PostgreSQL temporal y red aislada.

El arranque habitual necesita dos archivos privados:

| Archivo | Responsabilidad |
| --- | --- |
| `.env.docker` | Imagen, puertos y claves de Network y su PostgreSQL local. |
| `.env.render.corporativo` | Conexión en línea y variables de Corporate; la misma referencia privada que se utiliza para configurar Render. |

Se retiraron las variantes Compose local/en-linea/prod y los archivos
`.env.docker.corporativo`, `.env.docker.en-linea`, `.env.docker.produccion` y sus
dos plantillas redundantes. Las versiones anteriores tienen un respaldo privado
en `logs/respaldo-configuracion-*`, ignorado por Git y excluido de la imagen.

`.env` y `.env.corporativo` se conservan para ejecutar directamente con Python.
Docker no los carga. Los archivos `.example` son plantillas sin credenciales reales.

## Arranque

Desde la carpeta del backend:

```powershell
python scripts/docker/iniciar.py
```

Desde otra carpeta:

```powershell
python "C:\Users\Desarrollador1\Desktop\VitaGo\backend\scripts\docker\iniciar.py"
```

El lanzador resuelve la raíz, usa `.venv` si existe, valida la configuración,
construye `vitago-backend:0.57.0`, inicia los servicios y espera sus healthchecks.
Ya no requiere `--modo` ni combinar varios Compose o archivos de variables.

| Servicio | Dirección en esta computadora | Base |
| --- | --- | --- |
| Corporate | http://127.0.0.1:8001/api/v1/ | PostgreSQL en línea, `vitago_corporativo` |
| Network | http://127.0.0.1:8000/api/v1/ | PostgreSQL Docker, `bd_network/vitago` |

Las APIs corren en esta computadora; «en línea» se refiere a la base Corporate.
El servicio público de Render sigue siendo un despliegue independiente.
El proyecto sigue llamándose `vitago`: reutiliza `vitago_datos_network`, las
redes y los puertos existentes. El antiguo volumen `vitago_datos_corporativos`
permanece conservado; no hay un servicio activo `bd_corporativa`.

En una instalación nueva, proporcionar primero el archivo privado Corporate.
El lanzador exige PostgreSQL externo y la base exclusiva `vitago_corporativo`.
Si falta `.env.docker`, lo genera desde `.env.docker.example` con cuatro secretos
independientes de Network. Nunca sobrescribe un archivo existente: las claves
ya guardadas en PostgreSQL deben mantenerse.

## Operación

```powershell
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f corporativo network
docker compose --env-file .env.docker down
```

`down` conserva los datos. No añadir `--volumes` si se quieren conservar las bases.
Para comprobar ambas conexiones:

```powershell
curl.exe http://127.0.0.1:8001/api/v1/salud/disponibilidad/
curl.exe http://127.0.0.1:8000/api/v1/salud/disponibilidad/
```

La disponibilidad ejecuta `SELECT 1` y devuelve 200 o 503; `/api/v1/salud/`
conserva su contrato previo. PostgreSQL no publica el puerto 5432 al host.
Para LAN o una web local, ajustar explícitamente `PUBLICAR_EN`,
`SERVIDORES_DOCKER` y `ORIGENES_WEB_DOCKER`; no se cambia IP ni firewall.

Antes de Gunicorn, el entrypoint espera PostgreSQL con plazo acotado, aplica las
migraciones pendientes bajo un advisory lock por base, prepara estáticos y usa
`exec` para iniciar el servidor. Un fallo detiene el arranque. Los comandos
administrativos no ejecutan esa preparación adicional. El arranque no importa
datos, crea cuentas ni cambia contraseñas.

La imagen utiliza Python 3.11, dependencias fijadas y un usuario sin privilegios.
No incluye `.env`, `.git`, volúmenes, fotos ni respaldos. Las fotografías Base64
permanecen en PostgreSQL; el mantenimiento mensual y la recuperación de jornadas
siguen activos. `collectstatic` prepara los estáticos; su publicación depende
del alojamiento si se utilizan vistas que los requieren.

Los plazos predeterminados siguen siendo: conexión 60 s, intervalo 2 s,
lock de migraciones 120 s, Gunicorn 60 s y dos trabajadores. Las variables
`APLICAR_MIGRACIONES` y `PREPARAR_ESTATICOS` siguen activadas por defecto.

## Mantenimiento de fotografías

La retención automática conserva el mes operativo actual y el anterior según
la zona horaria del servidor. Elimina contenido de imágenes, conservando filas,
solicitudes, evidencias y GPS. El servidor recupera las ejecuciones atrasadas.
Para revisar el mantenimiento sin aplicar cambios:

```powershell
docker compose --env-file .env.docker exec corporativo python manage.py mantener_imagenes --modo-esperado CORPORATIVO --simular
docker compose --env-file .env.docker exec network python manage.py mantener_imagenes --modo-esperado EXTERNO --simular
```

El comando dispone de `--confirmar` y `--conservar-originales` para las tareas
administrativas correspondientes. Los archivos anteriores necesitan su carpeta
disponible en el contenedor y RAIZ_ARCHIVOS configurado para importarlos; no se
incluyen en la imagen. Un original no encontrado se conserva como pendiente.

## Pruebas aisladas

La versión 0.57.0 separa el resumen mensual/quincenal de motoristas (una tabla,
promedio de temperatura de las lecturas reales) y los servicios diarios en
Excel/PDF. Los filtros de rango diario se retiran del resumen descargable.
Nuevo endpoint `GET /api/v1/reportes/servicios/descargar/`; contrato completo en
API 0.57. Conserva permisos y zonas operativas, sin modelos, dependencias,
variables ni migraciones nuevas. El frontend debe integrar los nuevos filtros.

La versión 0.56.0 reduce los reintentos innecesarios del GPS: consulta si hay
pendientes y algún motorista elegible antes de recorrer la cola. Al haber cupo,
conserva la selección por GPS y la validación transaccional; los reintentos
generales y el cierre diario conservan su funcionamiento. Las fotografías de
solicitudes/incidencias preparan el Base64 antes de bloquear las filas, verifican
de nuevo permisos/estado al guardar y conservan fecha oficial y bytes originales.
Sin dependencias, servicios, variables ni migraciones nuevas. Contrato API 0.56.

La versión 0.55.0 añade la política de captura GPS cercana: captura/envío cada
5 segundos al entrar a 250 metros de la próxima parada, salida a 350 metros.
La configuración y el objetivo autorizado se publican sin consultas adicionales
en mi-ruta. Flutter debe consumir esta política y abrir la evidencia con la llegada
recibida en el POST GPS. Los tres controles nuevos tienen valores predeterminados
en settings; la plantilla `.env.example` permite personalizarlos por servicio.
Sin nuevas dependencias, servicios ni migraciones. Contrato en API 0.55.

La versión 0.54.0 amplía la optimización al resto de consultas de la API:
usuarios y roles, sucursales y ubicaciones, vehículos, avisos, solicitudes,
jornadas, incidencias, seguimiento e historial de rutas. El cupo del motorista
consulta solo sus servicios activos mediante el índice existente, sin agrupar
todo su historial. Seguimiento y evidencias omiten historiales que no presentan;
el detalle completo los conserva. Sin servicios, variables o migraciones nuevas.
Pruebas de paginación y revocación en Corporate/Network; contrato en API0.54.

La versión0.53.0 reduce recorridos repetidos de las hojas Excel y cálculos de
maquetación PDF. Agrupa lecturas de permisos y limita las columnas de los reportes,
conservando autorización por petición. No añade servicios, variables ni
migraciones. El contrato HTTP se conserva; mediciones y alcance en API0.53.

La versión0.52.0 corrige textos largos de Excel y la continuidad de servicios en
PDF. Incorpora fuentes de respaldo en `apps/reportes/recursos/fuentes`, incluidas
por el mismo COPY de aplicaciones; no descarga fuentes al atender peticiones.
Se conservan sus licencias y procedencia. No añade paquetes de ejecución,
variables, servicios ni migraciones. El contrato0.52 documenta los límites
físicos de Excel y su error400 con clave `formato`, recomendando PDF.

La versión0.51.0 agrega el departamento fijo de operación administrado por país,
en Corporate y Network. El arranque aplica `repartidores.0005`; los perfiles
anteriores quedan sin cobertura hasta que un administrador la configure.
No reciben asignaciones nuevas mientras estén pendientes de esa configuración.
Los servicios e históricos existentes se conservan. Ver el contrato0.51 en
`VITAGO_API_FRONTEND.md` para integrar la configuración administrativa.

La versión0.50.0 añade reportes administrativos Excel/PDF y avisos de desvío.
Los radios, permanencia y calidad GPS pueden ajustarse con las variables
`DESVIACION_*` documentadas en `.env.docker.example`; `DESVIACIONES_AUTOMATICAS_HABILITADAS`
permite desactivar la detección. Se pasan a ambas APIs. No se consulta Google al
recibir GPS o descargar reportes. Contrato y cambios que requiere el cliente
en la sección0.50 de `VITAGO_API_FRONTEND.md`.

```powershell
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from pruebas
docker compose -f docker-compose.test.yml down
```

Este Compose no carga archivos privados ni publica puertos. Utiliza PostgreSQL
en tmpfs y solo acepta `bd_pruebas/vitago_pruebas_docker`; crea y elimina la
base temporal `test_vitago_docker`. Bloquea llamadas reales a Google. Sus
credenciales sintéticas no corresponden a bases operativas.

## Imagen publicada y despliegue

El mismo Compose admite una imagen publicada: establecer su referencia versionada
en `IMAGEN_BACKEND` y `POLITICA_DESCARGA_IMAGEN=always` dentro de `.env.docker`.
Después ejecutar:

```powershell
python scripts/docker/iniciar.py --sin-construir
```

Con `never`, la imagen debe existir en este host. Para iniciar solo Corporate:

```powershell
docker compose --env-file .env.docker up -d --no-build --wait corporativo
```

En un servidor con proxy HTTPS propio, configurar `REDIRECCION_SSL_DOCKER=true`
y `CONFIAR_PROXY_HTTPS_DOCKER=true` en su copia de `.env.docker` y autorizar hosts
y orígenes concretos en el archivo privado de cada aplicación. Esta computadora
conserva HTTP sobre 127.0.0.1. Network conserva su PostgreSQL local separado.

Render puede construir directamente el `Dockerfile`, sin Compose: runtime Docker,
contexto raíz del backend, sin reemplazar CMD/entrypoint,
`DJANGO_SETTINGS_MODULE=config.settings.contenedor` y healthcheck
`/api/v1/salud/disponibilidad/`. Sus variables se cargan en el panel Environment;
`.env.render.corporativo` es una referencia privada local, no se copia a la imagen.
Render proporciona `PORT` y su proxy HTTPS. El entrypoint aplica migraciones;
no duplicarlas en Build o Pre-Deploy. Esta simplificación no publica imágenes
ni modifica los despliegues de Render o Vercel.
