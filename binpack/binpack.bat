@echo off
rem binpack wrapper - keeps the console in UTF-8 so CJK paths survive.
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
python "%~dp0binpack.py" %*
endlocal & exit /b %errorlevel%