@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=py
where py >nul 2>nul || set PY=python
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
%PY% app.py
