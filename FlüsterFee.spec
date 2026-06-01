# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('tray_icon.png', '.')],
    hiddenimports=[
        # ── app modules ────────────────────────────────────────────────────
        'ssl_setup',
        'config',
        'recorder',
        'whisper_client',
        'llm_corrector',
        'text_inserter',
        'vocabulary',
        'tray',
        # ── ui modules ─────────────────────────────────────────────────────
        'ui',
        'ui.dock',
        'ui.settings_dialog',
        'ui.theme',
        'ui.translations',
        'ui.utils',
        # ── truststore / SSL ───────────────────────────────────────────────
        # truststore uses ctypes to call Win32 CryptoAPI — no DLLs needed,
        # but PyInstaller must bundle the Python package.
        'truststore',
        '_ssl',
        'ssl',
        # ── requests / certifi ────────────────────────────────────────────
        'certifi',
        'requests',
        'urllib3',
        'charset_normalizer',
        # ── sounddevice / numpy ────────────────────────────────────────────
        'sounddevice',
        'soundfile',
        'numpy',
        # ── keyring (Windows Credential Manager) ──────────────────────────
        'keyring',
        'keyring.backends.Windows',
    ],
    hookspath=[],
    hooksconfig={},
    # pyi_rth_ssl.py runs before app.py and patches ssl.SSLContext so that
    # all HTTPS traffic goes through the Windows Trust Store.  This handles
    # Cisco Secure Client / Umbrella TLS inspection transparently.
    runtime_hooks=['pyi_rth_ssl.py'],
    excludes=[
        'tkinter',
    ],
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
    name='FlüsterFee',
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
