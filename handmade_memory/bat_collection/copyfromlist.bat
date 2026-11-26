@echo off
chcp 65001
setlocal enabledelayedexpansion

set "file_list=%~1"
set "dest_dir=%~2"

:: Set default if not provided
if "%file_list%"=="" set file_list=list.txt
if "%dest_dir%"=="" set dest_dir=.

:: 检查list.txt是否存在
if not exist "!file_list!" (
    echo error: can't find "!file_list!"
    pause
    exit /b 1
)

for /f "delims=" %%a in (!file_list!) do (
    :: 检查文件是否存在
    if exist "%%a" (
        echo copying："%%a"
        copy "%%a" "!dest_dir!" >nul
        if !errorlevel! equ 0 (
            echo sucess
        ) else (
            echo fail
        )
    ) else (
        echo warning: file "%%a" don't exist, skip
    )
    echo.
)

echo complete