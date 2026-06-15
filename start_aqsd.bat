@echo off
:: Start qBittorrent (skip if already running)
tasklist /FI "IMAGENAME eq qbittorrent.exe" 2>NUL | find /I /N "qbittorrent.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    start "" "C:\Program Files (x86)\qBittorrent\qbittorrent.exe"
    :: Wait for qB to be ready
    timeout /t 5 /nobreak >NUL
)

:: Start AQSD server
cd /d "F:\a_课件\anime-qb-smart-downloader"
C:\Python314\python -m aqsd.main server >> logs\server.log 2>&1
