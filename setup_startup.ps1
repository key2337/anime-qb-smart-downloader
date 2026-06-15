$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'AQSD.lnk'
$targetPath = 'F:\a_课件\anime-qb-smart-downloader\start_aqsd.vbs'
$WScriptShell = New-Object -ComObject WScript.Shell
$shortcut = $WScriptShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = '//B "F:\a_课件\anime-qb-smart-downloader\start_aqsd.vbs"'
$shortcut.WindowStyle = 7
$shortcut.Description = 'AQSD+QB Auto Start'
$shortcut.Save()
Write-Output "Shortcut created at: $shortcutPath"
