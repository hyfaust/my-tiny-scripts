@echo off
rem Thin wrapper: all path handling lives in Julia, whose cd is drive-aware on
rem Windows and accepts relative paths. Argument 1 = server working directory.
setlocal

set "WD=%~1"
if "%WD%"=="" set "WD=F:\Users\code_data\julia"

rem A trailing backslash would escape the closing quote of the quoted argument.
if "%WD:~-1%"=="\" set "WD=%WD%\"

julia --project=@pluto -e "import Pluto; cd(ARGS[1]); Pluto.run()" "%WD%"