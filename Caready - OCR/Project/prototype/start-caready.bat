@echo off
REM ===================================================================
REM  Caready prototype - local server
REM
REM  Double-click this file. Leave the window open for the whole demo;
REM  closing it stops the server and the pages stop loading.
REM
REM  The port is fixed at 8000 on purpose. Browser storage is per-origin,
REM  so localhost:8001 would be a different site and none of the prepared
REM  demo data would be visible there.
REM ===================================================================

cd /d "%~dp0"

echo.
echo   Caready prototype server
echo   ------------------------
echo   Folder : %CD%
echo.

if not exist "caready-store.js" (
  echo   PROBLEM: caready-store.js is not in this folder.
  echo   The pages will load but submitting an inspection will fail.
  echo   Put caready-store.js next to inspector.html, then run this again.
  echo.
  pause
  exit /b 1
)

echo   Open these two in your browser:
echo     http://localhost:8000/inspector.html
echo     http://localhost:8000/dashboard.html
echo.
echo   Keep this window open. Ctrl+C or closing it stops the server.
echo.

python -m http.server 8000
if errorlevel 1 (
  echo.
  echo   Could not start. Either python is not on PATH, or port 8000
  echo   is already in use - check for another server window already open.
  echo.
  pause
)