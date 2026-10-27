param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Corporate', 'Network')]
    [string]$Modo,
    [switch]$Confirmar
)

$ErrorActionPreference = 'Stop'
if (-not $Confirmar) {
    throw 'Use -Confirmar para registrar una tarea nueva de avisos. No se modificaron tareas.'
}
$directorioBackend = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ejecutablePython = Join-Path $directorioBackend '.venv\Scripts\python.exe'
$ejecutableSinVentana = Join-Path $directorioBackend '.venv\Scripts\pythonw.exe'
$archivoManage = Join-Path $directorioBackend 'manage.py'
if ($Modo -eq 'Corporate') {
    $configuracion = 'config.settings.tarea_avisos_corporativa'
    $modoEsperado = 'CORPORATIVO'
    $archivoEntorno = Join-Path $directorioBackend '.env.corporativo'
} else {
    $configuracion = 'config.settings.tarea_avisos_network'
    $modoEsperado = 'EXTERNO'
    $archivoEntorno = Join-Path $directorioBackend '.env'
}
$archivoConfiguracion = Join-Path $directorioBackend ($configuracion.Replace('.', '\') + '.py')
foreach ($archivoRequerido in @($ejecutablePython, $ejecutableSinVentana, $archivoManage, $archivoEntorno, $archivoConfiguracion)) {
    if (-not (Test-Path -LiteralPath $archivoRequerido -PathType Leaf)) {
        throw "No existe el archivo requerido: $archivoRequerido"
    }
}
$nombreTarea = "VitaGo-$Modo-LimpiezaAvisos"
# Fallar también al no poder consultar tareas; no tratar acceso denegado como inexistencia.
$tareaExistente = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -eq $nombreTarea })
if ($tareaExistente.Count -gt 0) {
    throw "La tarea $nombreTarea ya existe. No se sobrescribe ninguna tarea."
}

# Solo lectura de la base correcta: la medianoche procede del reloj/zona Django,
# nunca del teléfono ni de la zona que haya seleccionado el usuario de Windows.
$salidaSimulacion = & $ejecutablePython $archivoManage archivar_notificaciones_vencidas "--settings=$configuracion" "--modo-esperado=$modoEsperado" --simular
if ($LASTEXITCODE -ne 0) {
    throw 'No se pudo validar el modo, esquema y zona del backend. No se registró la tarea.'
}
$simulacion = ($salidaSimulacion -join [Environment]::NewLine) | ConvertFrom-Json
$usuarioTarea = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$argumentos = '"' + $archivoManage + '" archivar_notificaciones_vencidas --settings=' + $configuracion + ' --modo-esperado=' + $modoEsperado + ' --confirmar'
$accion = New-ScheduledTaskAction -Execute $ejecutableSinVentana -Argument $argumentos -WorkingDirectory $directorioBackend
$medianoche = [DateTimeOffset]::Parse($simulacion.siguiente_corte_en)
$diario = New-ScheduledTaskTrigger -Daily -At $medianoche.LocalDateTime
# StartBoundary admite un desplazamiento UTC explícito (documentación Microsoft).
$diario.StartBoundary = $simulacion.siguiente_corte_en
$recuperacion = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$alIniciarSesion = New-ScheduledTaskTrigger -AtLogOn -User $usuarioTarea
$principal = New-ScheduledTaskPrincipal -UserId $usuarioTarea -LogonType Interactive -RunLevel Limited
$opciones = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $nombreTarea -Action $accion -Trigger @($diario, $recuperacion, $alIniciarSesion) -Principal $principal -Settings $opciones -Description "Archiva solo avisos anteriores al día del servidor ($($simulacion.zona_horaria_operativa)), medianoche y recuperación cada 15 minutos. Conserva solicitudes, GPS, evidencias e historial." | Out-Null
Write-Output "Registrada $nombreTarea. Medianoche del servidor: $($simulacion.siguiente_corte_en)."
Write-Output 'Sin ventana. Requiere PC encendida y sesión de Windows iniciada; recupera al volver. No modifica otras tareas.'
