@echo off
setlocal enabledelayedexpansion
echo FUNCTION:numbering from 1 to n
echo if you want to run the shell,press any button to continue
pause>nul
set a=1
for %%i in ("*") do (
ren "%%i" "!a!"
set /a a=a+1 
)
echo complete
pause>nul
exit