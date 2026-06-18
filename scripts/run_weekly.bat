@echo off
cd /d D:\Documents\GitHub\alpha_engine
"D:\miniforge3\python.exe" scripts\weekly_research.py --market us
"D:\miniforge3\python.exe" scripts\check_factor_decay.py --update-metadata
"D:\miniforge3\python.exe" scripts\generate_weekly_report.py