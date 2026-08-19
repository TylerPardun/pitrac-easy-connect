# Windows packaging specification for PyInstaller.

analysis = Analysis(
    ["packaging/companion_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    # PyInstaller cannot see these through the runtime lookups in the
    # service, so they are named explicitly.
    hiddenimports=[
        "pitrac_easy_connect.companion.service",
        "pitrac_easy_connect.companion.web",
        "pitrac_easy_connect.companion.link_client",
        "pitrac_easy_connect.companion.simulator_session",
        "pitrac_easy_connect.common.discovery",
        "pitrac_easy_connect.common.pairing_exchange",
        "pitrac_easy_connect.pi.pairing",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="PiTracCompanion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # A console window would confuse a beginner; the interface is the web page.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

