@echo off
ls | shuf -n 1 | xargs -I {} cmd /c start "" "{}"