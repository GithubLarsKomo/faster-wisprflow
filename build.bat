@echo off
python -m pip install --upgrade pip
pip install -r requirements.txt
uv run pyinstaller EuroWisprFlow.spec
pause