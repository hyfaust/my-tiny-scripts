@echo off 
chcp 65001>nul
for /d %%X in (*) do (rar a -df "%%X.rar" "%%X"&&rd "%%X")

echo.
echo complete
pause>nul
exit