@echo off 
chcp 65001>nul
taskkill /f /im explorer.exe 
CD /d %userprofile%\AppData\Local 
DEL IconCache.db /a 
start explorer.exe 
echo 执行完成 