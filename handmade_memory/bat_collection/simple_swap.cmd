@echo off
echo Simple File Swapper
echo.

if "%~1"=="" (
    echo Usage: %0 config.txt
    exit /b 1
)

set CONFIG=%1
set SUCCESS=0
set FAILED=0

echo Processing: %CONFIG%
echo.

for /f "tokens=1,2" %%a in (%CONFIG%) do (
    echo Swapping %%a and %%b
    
    ren "%%a" temp.tmp >nul
    if not errorlevel 1 (
        ren "%%b" "%%a" >nul
        if not errorlevel 1 (
            ren temp.tmp "%%b" >nul
            if not errorlevel 1 (
                echo   OK
                set /a SUCCESS+=1
            ) else (
                echo   FAIL
                ren "%%a" "%%b" >nul
                ren temp.tmp "%%a" >nul
                set /a FAILED+=1
            )
        ) else (
            echo   FAIL
            ren temp.tmp "%%a" >nul
            set /a FAILED+=1
        )
    ) else (
        echo   FAIL
        set /a FAILED+=1
    )
    echo.
)

echo Done!
echo Success: %SUCCESS%
echo Failed: %FAILED%