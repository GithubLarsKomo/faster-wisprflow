# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('tray_icon.png', '.')],
    hiddenimports=[
        'config',
        'recorder',
        'whisper_client',
        'llm_corrector',
        'text_inserter',
        'vocabulary',
        'correction_tracker',
        'tray',
        'ui',
        'ui.utils',
        'ui.overlay',
        'ui.popups',
        'ui.settings_window',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EuroWisprFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['tray_icon.ico'],
)
