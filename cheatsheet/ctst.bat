@echo off
setlocal enabledelayedexpansion

set "targetDir=E:\Mybat\cheatsheet"
set "returnPath=0"
set "cmdParam="

rem Parse arguments: support -p, -c <command>
:parseArgs
if "%~1"=="" goto :endParse
if /i "%~1"=="-p" (
    set "returnPath=1"
    shift
    goto :parseArgs
)
if /i "%~1"=="-c" (
    set "cmdParam=%~2"
    shift
    shift
    goto :parseArgs
)
set "searchName=%~1"
shift
goto :parseArgs
:endParse

if "%searchName%"=="" (
    if "%cmdParam%"=="" (
        explorer.exe "%targetDir%"
    ) else (
        echo Error: -c parameter requires a filename
        exit /b 1
    )
    exit /b
)

if not exist "%targetDir%" (
    echo Error: Directory %targetDir% does not exist
    exit /b 1
)

set "tempFile=%temp%\cheatsheet_match.txt"
dir /b "%targetDir%\*%searchName%*" > "%tempFile%" 2>nul

set "matchCount=0"
for /f "delims=" %%a in (%tempFile%) do set /a matchCount+=1

if !matchCount! equ 0 (
    echo No file matching "%searchName%" found.
    echo.
    echo Files in %targetDir%:
    dir /b "%targetDir%"
    del "%tempFile%" 2>nul
    exit /b 1
)

if !matchCount! equ 1 (
    for /f "delims=" %%a in (%tempFile%) do set "firstMatch=%%a"
    set "filePath=%targetDir%\!firstMatch!"

    if defined cmdParam (
        call :execCmd "!cmdParam!" "!filePath!"
    ) else if !returnPath! equ 1 (
        echo !filePath!
    ) else (
        echo Found: !firstMatch!
        start "" "!filePath!"
    )
    del "%tempFile%" 2>nul
    exit /b
)

rem Multiple matches
echo Found !matchCount! matching file(s):
echo.
set "n=0"
for /f "delims=" %%a in (%tempFile%) do (
    set /a n+=1
    echo   !n!. %%a
)
echo.

if defined cmdParam (
    set /p sel="Enter file number (1-!matchCount!), or press Enter to cancel): "
    if "!sel!"=="" goto :end
    if !sel! gtr !matchCount! goto :end
    if !sel! lss 1 goto :end

    set "n=0"
    for /f "delims=" %%a in (%tempFile%) do (
        set /a n+=1
        if !n! equ !sel! (
            set "filePath=%targetDir%\%%a"
            call :execCmd "!cmdParam!" "!filePath!"
        )
    )
) else if !returnPath! equ 1 (
    set /p sel="Enter file number (1-!matchCount!), or press Enter to cancel): "
    if "!sel!"=="" goto :end
    if !sel! gtr !matchCount! goto :end
    if !sel! lss 1 goto :end

    set "n=0"
    for /f "delims=" %%a in (%tempFile%) do (
        set /a n+=1
        if !n! equ !sel! echo %targetDir%\%%a
    )
) else (
    set /p sel="Enter file number to open (1-!matchCount!), or press Enter to cancel): "
    if "!sel!"=="" goto :end
    if !sel! gtr !matchCount! goto :end
    if !sel! lss 1 goto :end

    set "n=0"
    for /f "delims=" %%a in (%tempFile%) do (
        set /a n+=1
        if !n! equ !sel! start "" "%targetDir%\%%a"
    )
)

:end
del "%tempFile%" 2>nul
exit /b

:execCmd
setlocal
set "cmd=%~1"
set "fpath=%~2"
set "tempBat=%temp%\cheatsheet_exec_%random%.bat"
set "tempPs=%temp%\cheatsheet_replace_%random%.ps1"

rem Check if command contains {} placeholder
set "hasPlaceholder=0"
echo !cmd! | find "{}" >nul && set "hasPlaceholder=1"

if !hasPlaceholder! equ 1 (
    rem Has {} placeholder - use PowerShell for reliable replacement
    (
        echo param^([string]$cmd, [string]$path^)
        echo $cmd -replace '\{\}', $path
    ) > "!tempPs!"
    for /f "delims=" %%r in ('powershell -NoProfile -File "!tempPs!" "!cmd!" "!fpath!"') do set "finalCmd=%%r"
    echo !finalCmd! > "!tempBat!"
    del "!tempPs!" 2>nul
) else (
    rem No placeholder - append path at the end
    echo !cmd! "!fpath!" > "!tempBat!"
)

call "!tempBat!"
del "!tempBat!" 2>nul
endlocal
exit /b
