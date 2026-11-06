@echo off
rem Uruchamia strone gearwatch (http://localhost:8000). Zamkniecie okna = zatrzymanie strony.
cd /d "%~dp0"
".venv\Scripts\python.exe" web.py
pause
