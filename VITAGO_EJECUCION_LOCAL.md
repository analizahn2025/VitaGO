# Ejecución local de VitaGo Corporate y VitaGo Network

## 1. Aislamiento

Los dos productos usan el mismo código fuente, pero procesos y bases de datos
separados:

| Producto | Modo | Proveedor local | Base de datos | Puerto |
|---|---|---|---|---:|
| VitaGo Network | `EXTERNO` | `LOCAL` | `vitago` | `8000` |
| VitaGo Corporate | `CORPORATIVO` | `LOCAL` temporal | `vitago_corporativo` | `8001` |

No se utilizan esquemas compartidos. Las sesiones, usuarios y datos de un
producto no existen en la base del otro.

## 2. Archivos de entorno

- `.env`: configuración local de VitaGo Network.
- `.env.corporativo`: diferencias locales de VitaGo Corporate.
- `.env.corporativo.example`: plantilla sin credenciales reales.

`ARCHIVO_ENTORNO_ADICIONAL` solo admite archivos `.env.*` ubicados en la raíz
del backend. El archivo adicional sobrescribe valores del `.env` base.

## 3. Crear la base corporativa

El rol de aplicación `vitago` no posee permiso para crear bases. Desde `psql`
con el usuario administrador `postgres`, ejecutar una sola vez:

```sql
CREATE DATABASE vitago_corporativo OWNER vitago;
```

No es necesario compartir la contraseña de `postgres` con el backend ni con
Codex.

## 4. Aplicar migraciones a Corporate

En una terminal nueva, ubicada en la carpeta del backend:

```powershell
$env:ARCHIVO_ENTORNO_ADICIONAL=".env.corporativo"
.\.venv\Scripts\python.exe manage.py migrate
```

Verificación:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

## 5. Iniciar VitaGo Network

En una terminal sin `ARCHIVO_ENTORNO_ADICIONAL`:

```powershell
Remove-Item Env:ARCHIVO_ENTORNO_ADICIONAL -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Desde otro equipo de la red, la URL utiliza la IP local del servidor y el
puerto `8000`.

## 6. Iniciar VitaGo Corporate

En otra terminal:

```powershell
$env:ARCHIVO_ENTORNO_ADICIONAL=".env.corporativo"
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001
```

Desde otro equipo de la red, la URL utiliza la misma IP local, pero el puerto
`8001`.

## 7. Autenticación corporativa futura

La autenticación local de Corporate es exclusivamente temporal. Producción
rechaza esta combinación. Cuando el sistema central esté disponible, Corporate
usará:

```env
PROVEEDOR_AUTENTICACION=JWT_CORPORATIVO
```

Los perfiles, empresas, roles y permisos locales permanecerán asociados al
mismo usuario; se retirará la contraseña local y se registrará su identificador
corporativo.

## 8. Cuentas de prueba de Analiza

Para preparar las pantallas locales de solicitante y motorista, ejecutar una
sola vez desde la carpeta del backend:

```powershell
$env:ARCHIVO_ENTORNO_ADICIONAL=".env.corporativo"
.\.venv\Scripts\python.exe manage.py crear_usuarios_prueba --confirmar
```

El comando solo admite Corporate local con autenticación `LOCAL` y la base
`vitago_corporativo`. Crea `solicitante.prueba@analiza.test`,
`motorista.prueba@analiza.test`, el perfil operativo de este último y un
vehículo de prueba. Muestra las contraseñas generadas una vez en la terminal;
no las conserva en este documento ni reemplaza cuentas existentes.

Las cuentas son de desarrollo. La base necesita sucursales y ubicaciones
autorizadas antes de poder registrar solicitudes entre sucursales.

## 9. Escenario ficticio de sucursales y solicitudes

Después de crear las cuentas de prueba, preparar el escenario de Corporate:

```powershell
$env:ARCHIVO_ENTORNO_ADICIONAL=".env.corporativo"
.\.venv\Scripts\python.exe manage.py crear_datos_prueba_corporativo --confirmar
```

El comando solo admite `vitago_corporativo` en Corporate local con
autenticación `LOCAL`. Es repetible: no duplica registros ni modifica las
contraseñas o el estado de solicitudes ya creadas. Para la asignación inicial
requiere que el motorista de prueba esté disponible y tenga una jornada
activa. No afecta Network.

Crea tres ubicaciones ficticias aprobadas para Analiza: «Prueba - Sucursal
Centro», «Prueba - Sucursal Norte» y «Prueba - Empresa de transporte». Las dos
sucursales están en Tegucigalpa para probar `ENTRE_SUCURSALES`; el tercer
destino permite probar `EMPRESA_TRANSPORTE`. También crea una solicitud
pendiente entre sucursales y otra asignada al motorista de prueba hacia la
empresa de transporte. Los identificadores y números de solicitud se muestran
en la terminal al ejecutar el comando.

Las direcciones y coordenadas son ficticias. No utilizarlas para validar
rutas, kilometraje, tiempos de Google Maps ni operaciones reales. El comando
no borra los datos de prueba.
