@echo off
"%~dp0EO129.exe" play
if errorlevel 1 goto finish
"%~dp0Patch PW Networking Protocol.exe" --no-pause
:finish
set "EO129_EXIT=%ERRORLEVEL%"
echo.
set /p "EO129_WAIT=Press Enter to continue..."
exit /b %EO129_EXIT%
