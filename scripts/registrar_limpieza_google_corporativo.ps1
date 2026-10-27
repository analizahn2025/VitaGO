param([switch]$Confirmar)

$ErrorActionPreference = 'Stop'
if (-not $Confirmar) {
    throw 'Use -Confirmar para registrar la tarea de limpieza Google Corporate. No se modificaron tareas.'
}
$directorioBackend = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ejecutablePython = Join-Path $directorioBackend '.venv\Scripts\pythonw.exe'
$archivoManage = Join-Path $directorioBackend 'manage.py'
$archivoEntorno = Join-Path $directorioBackend '.env.corporativo'
$archivoConfiguracion = Join-Path $directorioBackend 'config\settings\tarea_limpieza_google_corporativa.py'
foreach ($archivoRequerido in @($ejecutablePython, $archivoManage, $archivoEntorno, $archivoConfiguracion)) {
    if (-not (Test-Path -LiteralPath $archivoRequerido -PathType Leaf)) {
        throw "No existe el archivo requerido: $archivoRequerido"
    }
}
$nombreTarea = 'VitaGo-Corporate-LimpiezaGoogle'
if (Get-ScheduledTask -TaskName $nombreTarea -ErrorAction SilentlyContinue) {
    throw 'La tarea ya existe. Este script no la sobrescribe; revise su configuración.'
}
$usuarioTarea = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$argumentos = '"' + $archivoManage + '" limpiar_rutas_google_vencidas --settings=config.settings.tarea_limpieza_google_corporativa --confirmar-corporativo'
$accion = New-ScheduledTaskAction -Execute $ejecutablePython -Argument $argumentos -WorkingDirectory $directorioBackend
$repeticion = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 1)
$alIniciarSesion = New-ScheduledTaskTrigger -AtLogOn -User $usuarioTarea
$principal = New-ScheduledTaskPrincipal -UserId $usuarioTarea -LogonType Interactive -RunLevel Limited
$opciones = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $nombreTarea -Action $accion -Trigger @($repeticion, $alIniciarSesion) -Principal $principal -Settings $opciones -Description 'Limpia solo geometrías Google vencidas de Corporate cada hora y al iniciar sesión; sin consultas externas ni borrado de auditoría.' | Out-Null
Write-Output 'Limpieza Google Corporate registrada cada hora y al iniciar sesión, sin ventana ni consultas facturables.'
Write-Output 'Requiere PC encendida y sesión iniciada; recupera la limpieza al volver. No cambia la tarea de cierre diario.'
