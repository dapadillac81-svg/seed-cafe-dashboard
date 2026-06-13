# Actualizacion nocturna del dashboard Seed Cafe.
# Se ejecuta cada noche (via Programador de tareas de Windows) despues de que
# "cowork" descarga el nuevo reporte de RecoPOS a la carpeta data/.
#
# Pasos:
#   1. Regenera docs/ (dashboard + plan de produccion) con generate_report.py
#   2. Si hubo cambios, hace commit y push al repo de GitHub

$proyecto = "C:\Users\seedc\OneDrive\اسناد\cafeteria\Claude\Reporte diario CODE"
$log = Join-Path $proyecto "nightly_update.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Set-Location $proyecto
Log "=== Inicio actualizacion nocturna ==="

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
$cambios = git status --porcelain -- docs/
if ($cambios) {
    git add docs/ *>> $log
    git commit -m "Reporte automatico nocturno: actualiza dashboard y pronostico" *>> $log
    git push *>> $log
    Log "Cambios publicados."
} else {
    Log "Sin cambios nuevos, no se publica nada."
}

Log "=== Fin actualizacion nocturna ==="
