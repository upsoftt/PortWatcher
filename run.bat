@echo off
cd /d "%~dp0"
echo Installing requirements...
pip install psutil pystray pillow
echo Starting Port Watcher...
start pythonw port_watcher.py
exit
