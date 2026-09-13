@echo off
cd /d "%~dp0code\experiment_pipelines"
"C:\Users\lauze\miniconda3\python.exe" monitor_tiering.py %*
