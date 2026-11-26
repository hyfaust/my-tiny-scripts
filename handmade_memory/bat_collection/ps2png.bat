@echo off
chcp 65001

set OUTPUT_FORMAT=%～1
if "%~1"=="" set OUTPUT_FORMAT=png
:: set "PSTOEDIT=C:\Program Files\pstoedit\pstoedit.exe"
set PSTOEDIT=magick

echo.
echo ==================================================
echo output_format:%OUTPUT_FORMAT%
echo.

for %%i in (*.ps) do ( 
%PSTOEDIT% -density 300 "%%i" "%%~ni.%OUTPUT_FORMAT%"
echo processing: %%i 
)


echo Complete
echo.
echo ==================================================

pause>nul