# install_shortcut.ps1 -- ASCII pur (PowerShell 5.1 / cp1252 safe)
# Cree ou supprime le raccourci bureau InsertYourCoin.lnk
# Usage :
#   install_shortcut.ps1              -- cree le raccourci
#   install_shortcut.ps1 -Uninstall   -- supprime le raccourci

param(
    [switch]$Uninstall
)

# Racine du projet : dossier parent de scripts/
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LancerBat   = Join-Path $ProjectRoot "lancer.bat"
$IcoPath     = Join-Path $ProjectRoot "assets\insertyourcoin.ico"
$Desktop     = [Environment]::GetFolderPath('Desktop')
$LinkPath    = Join-Path $Desktop "InsertYourCoin.lnk"

if ($Uninstall) {
    if (Test-Path $LinkPath) {
        Remove-Item $LinkPath -Force
        Write-Host "Raccourci supprime : $LinkPath"
    } else {
        Write-Host "Raccourci absent, rien a supprimer : $LinkPath"
    }
    exit 0
}

# Verification que les fichiers cibles existent
if (-not (Test-Path $LancerBat)) {
    Write-Error "lancer.bat introuvable : $LancerBat"
    exit 1
}
if (-not (Test-Path $IcoPath)) {
    Write-Warning "Icone introuvable : $IcoPath -- raccourci cree sans icone personnalisee."
    $IcoPath = ""
}

$WshShell  = New-Object -ComObject WScript.Shell
$Shortcut  = $WshShell.CreateShortcut($LinkPath)
$Shortcut.TargetPath       = $LancerBat
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description      = "InsertYourCoin - lance le tableau de bord local"
if ($IcoPath -ne "") {
    $Shortcut.IconLocation = "$IcoPath,0"
}
$Shortcut.Save()

Write-Host "Raccourci cree : $LinkPath"
Write-Host "  Cible         : $LancerBat"
Write-Host "  Repertoire    : $ProjectRoot"
if ($IcoPath -ne "") {
    Write-Host "  Icone         : $IcoPath"
}
Write-Host "Double-clic sur l'icone du bureau pour lancer InsertYourCoin."
