@echo off
python "%~dp0..\tools\build_art.py" %*
exit /b %errorlevel%
