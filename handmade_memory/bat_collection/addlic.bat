@echo off
setlocal
set "GPL_PATH=%~dp0GPL-3.txt"
set "GFDL_PATH=%~dp0GFDL-1.3-no-invariants-only.txt"
set "MIT_PATH=%~dp0LICENSE.MIT.txt"
set "WTFPL_PATH=%~dp0LICENSE.WTFPL.txt"

rem set default license
set "LIC_PATH=%GPL_PATH%"

if /i "%~1"=="GPL"  set "LIC_PATH=%GPL_PATH%"
if /i "%~1"=="GFDL" set "LIC_PATH=%GFDL_PATH%"
if /i "%~1"=="MIT"  set "LIC_PATH=%MIT_PATH%"
if /i "%~1"=="WTFPL" set "LIC_PATH=%WTFPL_PATH%"

if not exist "%LIC_PATH%" (
    echo error: license file not found: %LIC_PATH% 1>&2
    exit /b 1
)

copy /y "%LIC_PATH%" ".\LICENSE" >nul || (
    echo error: copy failed 1>&2
    exit /b 1
)
echo success: copied "%LIC_PATH%" to ".\LICENSE"
endlocal