@echo off
rem Importuje nowe zrzuty z Pobranych, przelicza kategorie i sprawdza alerty.
cd /d "%~dp0"
".venv\Scripts\python.exe" refresh.py
pause
