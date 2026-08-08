# install_shortcut.ps1 -- ASCII pur (PowerShell 5.1 / cp1252 safe)
# Cree ou supprime le raccourci bureau InsertYourCoin.lnk
# Usage :
#   install_shortcut.ps1              -- cree le raccourci
#   install_shortcut.ps1 -Uninstall   -- supprime le raccourci
#
# Le raccourci cible pythonw.exe DIRECTEMENT (pas lancer.bat) : pythonw.exe est
# le sous-systeme GUI de Python, il ne cree JAMAIS de fenetre console -- meme
# pas un flash bref. C'est la seule facon d'obtenir un double-clic a ZERO
# fenetre (un .bat, meme optimise, force toujours Explorer a ouvrir une console
# cmd.exe le temps de l'interpreter -- flash inevitable avec un .bat).

param(
    [switch]$Uninstall
)

# Racine du projet : dossier parent de scripts/
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LancerPy    = Join-Path $ProjectRoot "lancer.py"
$VenvPyw     = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
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
if (-not (Test-Path $LancerPy)) {
    Write-Error "lancer.py introuvable : $LancerPy"
    exit 1
}

# pythonw.exe : prefere le venv du projet ; sinon cherche un pythonw sur le PATH.
if (Test-Path $VenvPyw) {
    $PyW = $VenvPyw
} else {
    $Found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($Found) {
        $PyW = $Found.Source
    } else {
        Write-Error "pythonw.exe introuvable (ni dans .venv, ni sur le PATH). Cree le venv (SETUP.md section 3) puis relance ce script."
        exit 1
    }
}

if (-not (Test-Path $IcoPath)) {
    Write-Warning "Icone introuvable : $IcoPath -- raccourci cree sans icone personnalisee."
    $IcoPath = ""
}

$WshShell  = New-Object -ComObject WScript.Shell
$Shortcut  = $WshShell.CreateShortcut($LinkPath)
$Shortcut.TargetPath       = $PyW
$Shortcut.Arguments        = '"' + $LancerPy + '"'
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description      = "InsertYourCoin - lance le tableau de bord local (sans fenetre console)"
if ($IcoPath -ne "") {
    $Shortcut.IconLocation = "$IcoPath,0"
}
$Shortcut.Save()

Write-Host "Raccourci cree : $LinkPath"
Write-Host "  Cible         : $PyW"
Write-Host "  Argument      : $LancerPy"
Write-Host "  Repertoire    : $ProjectRoot"
if ($IcoPath -ne "") {
    Write-Host "  Icone         : $IcoPath"
}
Write-Host "Double-clic sur l'icone du bureau pour lancer InsertYourCoin (aucune fenetre console)."
