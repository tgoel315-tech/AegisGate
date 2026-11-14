@echo off
title Push AegisGate to GitHub
echo ========================================================
echo   Pushing AegisGate changes to GitHub...
echo   Repository: https://github.com/tgoel315-tech/AegisGate
echo   Collaborator: Abhinav-Bisht-17
echo ========================================================
echo.
cd /d "%~dp0"
git push origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo   [SUCCESS] Code pushed successfully to GitHub!
    echo ========================================================
) else (
    echo ========================================================
    echo   [ACTION REQUIRED] If GitHub prompted you to sign in,
    echo   please click "Sign in with your browser" to authorize.
    echo ========================================================
)
echo.
pause
