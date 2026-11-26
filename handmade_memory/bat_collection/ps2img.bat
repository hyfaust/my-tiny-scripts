@echo off
chcp 65001

set OUTPUT_FORMAT=%～1
if "%~1"=="" set OUTPUT_FORMAT=emf

:: set "PSTOEDIT=C:\Program Files\pstoedit\pstoedit.exe"
set PSTOEDIT=pstoedit

echo.
echo ==================================================
echo output_format:%OUTPUT_FORMAT%
echo.

for %%i in (*.ps) do ( 
%PSTOEDIT% -q -f %OUTPUT_FORMAT% "%%i" "%%~ni.%OUTPUT_FORMAT%"
echo processing: %%i 
)


echo Complete
echo.
echo ==================================================

pause>nul