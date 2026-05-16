@echo off
python -m pip install --upgrade pip
pip install -r requirements.txt
.venv\Scripts\pyinstaller.exe FlüsterFee.spec
pause