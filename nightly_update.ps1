# Actualizacion nocturna del dashboard Seed Cafe.
# Se ejecuta cada noche (via Programador de tareas de Windows) despues de que
# "cowork" descarga el nuevo reporte de RecoPOS a la carpeta data/, y/o
# despues de que la tarea "recopos-cierre-diario" genera cierre_YYYY-MM-DD.txt.
#
# Pasos:
#   1. Copia los cierre_*.txt nuevos desde la carpeta de cowork a data_txt/
#   2. Regenera docs/ (dashboard + plan de produccion) con generate_report.py
#   3. Si hubo cambios, hace commit y push al repo de GitHub

$proyecto = "C:\Users\seedc\OneDrive\اسناد\cafeteria\Claude\Reporte diario CODE"
$log = Join-Path $proyecto "nightly_update.log"
$coworkFolder = "C:\Users\seedc\Claude\Projects\Bajada de reportes de venta de Recopos"
$dataTxt = Join-Path $proyecto "data_txt"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Set-Location $proyecto
Log "=== Inicio actualizacion nocturna ==="

if (-not (Test-Path $dataTxt)) {
    New-Item -ItemType Directory -Path $dataTxt | Out-Null
}
if (Test-Path $coworkFolder) {
    Get-ChildItem -Path $coworkFolder -Filter "cierre_*.txt" | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $dataTxt -Force
        Log "Copiado $($_.Name) a data_txt/"
    }
}

$env:PYTHONIOENCODING = "utf-8"
# Evita que los warnings normales de openpyxl (no son errores) se traten
# como NativeCommandError al redirigir la salida.
$env:PYTHONWARNINGS = "ignore"

python generate_report.py *>> $log
if ($LASTEXITCODE -ne 0) {
    Log "ERROR generando el reporte (exit code $LASTEXITCODE)"
    exit 1
}

# Hay cambios para commitear?
$cambios = git status --porcelain -- docs/ data_txt/
if ($cambios) {
    git add docs/ data_txt/ *>> $log
    git commit -m "Reporte automatico nocturno: actualiza dashboard y pronostico" *>> $log
    git push *>> $log
    Log "Cambios publicados."
} else {
    Log "Sin cambios nuevos, no se publica nada."
}

Log "=== Fin actualizacion nocturna ==="
