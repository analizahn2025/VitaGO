param([switch]$Confirmar)

$ErrorActionPreference = 'Stop'
if (-not $Confirmar) {
    throw 'Para registrar la tarea local use -Confirmar. No se modificó el Programador de tareas.'
}
$directorioBackend = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ejecutablePython = Join-Path $directorioBackend '.venv\Scripts\pythonw.exe'
$archivoManage = Join-Path $directorioBackend 'manage.py'
$archivoEntorno = Join-Path $directorioBackend '.env.corporativo'
foreach ($archivoRequerido in @($ejecutablePython, $archivoManage, $archivoEntorno)) {
    if (-not (Test-Path -LiteralPath $archivoRequerido -PathType Leaf)) {
        throw "No existe el archivo requerido: $archivoRequerido"
    }
}
$nombreTarea = 'VitaGo-Corporate-CierreDiario'
if (Get-ScheduledTask -TaskName $nombreTarea -ErrorAction SilentlyContinue) {
    throw 'La tarea ya existe. Revísela antes de reemplazarla; este script no la sobrescribe.'
}
$usuarioTarea = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$argumentos = '"' + $archivoManage + '" cerrar_operaciones_vencidas --settings=config.settings.tarea_corporativa --confirmar-corporativo'
$accion = New-ScheduledTaskAction -Execute $ejecutablePython -Argument $argumentos -WorkingDirectory $directorioBackend
$repeticion = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$alIniciarSesion = New-ScheduledTaskTrigger -AtLogOn -User $usuarioTarea
$principal = New-ScheduledTaskPrincipal -UserId $usuarioTarea -LogonType Interactive -RunLevel Limited
$opciones = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $nombreTarea -Action $accion -Trigger @($repeticion, $alIniciarSesion) -Principal $principal -Settings $opciones -Description 'Cierre Corporate por zona horaria del país, recuperación de días vencidos y servicios de usuarios suspendidos.' | Out-Null
Write-Output 'Tarea registrada. Corre cada minuto con la sesión de Windows iniciada, sin ventana ni servidor adicional.'
Write-Output 'Con la PC apagada, dormida o sin sesión no puede ejecutarse; recupera pendientes al volver a iniciar sesión.'
