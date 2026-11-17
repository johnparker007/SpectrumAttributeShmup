@echo off
setlocal
pushd "%~dp0"

set "ASSEMBLER=%SJASMPLUS%"
if not defined ASSEMBLER for %%I in (sjasmplus.exe) do set "ASSEMBLER=%%~$PATH:I"
if not defined ASSEMBLER set "ASSEMBLER=%USERPROFILE%\Desktop\_temp\sjasmplus-1.20.2.win\sjasmplus.exe"

if not exist "%ASSEMBLER%" (
    echo Could not find SjASMPlus.
    echo Set SJASMPLUS to the full path of your sjasmplus.exe and try again.
    set "BUILD_RESULT=1"
    goto finish
)

echo Rebuilding the game with the latest artwork...
python tools\build_game.py --assembler "%ASSEMBLER%"
set "BUILD_RESULT=%ERRORLEVEL%"
if "%BUILD_RESULT%"=="0" (
    echo.
    echo Ready to play: %~dp0build\game.tap
) else (
    echo.
    echo Build failed. See the error above.
)

:finish
popd
echo.
pause
exit /b %BUILD_RESULT%
