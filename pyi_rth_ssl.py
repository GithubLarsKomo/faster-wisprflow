# PyInstaller runtime hook — executed by the bootloader before app.py.
# Patches ssl.SSLContext to use the Windows Trust Store so that requests
# made against corporate HTTPS endpoints (OpenRouter, Groq, Ollama behind a
# Cisco / Umbrella TLS-inspection proxy) verify correctly.
#
# This file is referenced by `runtime_hooks` in FlüsterFee.spec.

try:
    import truststore          # available if bundled as a hidden import
    truststore.inject_into_ssl()
except Exception:
    # Fallback: stdlib-only Windows cert export sets REQUESTS_CA_BUNDLE
    try:
        import ssl_setup       # bundled app module
        ssl_setup.init()
    except Exception:
        pass
