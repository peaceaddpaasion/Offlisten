@echo off
rem Launcher. The venv must live next to this file (see README: one-time setup).
rem Usage: run_transcriber.bat live --source loopback
rem        run_transcriber.bat srt meeting.wav
set PY=%~dp0.venv\Scripts\python.exe
"%PY%" pc_transcriber.py %*
