@echo off
"%~dp0EO129.exe" play
set "EO129_EXIT=%ERRORLEVEL%"
echo.
set /p "EO129_WAIT=Press Enter to continue..."
exit /b %EO129_EXIT%
