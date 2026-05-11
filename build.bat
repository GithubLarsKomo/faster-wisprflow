@echo off
python -m pip install --upgrade pip
pip install -r requirements.txt
uv run pyinstaller --onefile --noconsole --name EuroWisprFlow --add-data "tray_icon.png;." --icon tray_icon.ico app.py
pause