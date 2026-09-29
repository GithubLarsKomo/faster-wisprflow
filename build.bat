@echo off
setlocal

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv is required. Install uv and retry.
    exit /b 1
)

uv sync --frozen
if errorlevel 1 exit /b 1

uv run pyinstaller FlüsterFee.spec
if errorlevel 1 exit /b 1

echo.
echo Build complete: dist\FlüsterFee.exe
endlocal
