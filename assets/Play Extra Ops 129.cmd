@echo off
"%~dp0EO129.exe" play
set "EO129_EXIT=%ERRORLEVEL%"
echo.
timeout /t 5 /nobreak
exit /b %EO129_EXIT%
