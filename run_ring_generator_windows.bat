@echo off
cd /d "%~dp0"
py -3.8 ring_generator_gui.py
if errorlevel 1 pause
