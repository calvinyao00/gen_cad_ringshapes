@echo off
cd /d "%~dp0"
py ring_generator_gui.py
if errorlevel 1 pause
