# -*- mode: python ; coding: utf-8 -*-
"""
Minimal PyInstaller build for Playlist Fixer.

Important: do NOT use collect_all("PySide6"). PyInstaller's PySide6 hooks
will collect the QtCore/QtGui/QtWidgets libraries and platform plugins used
by the imports in the application. Collecting the whole PySide6 package
also bundles WebEngine, QML, 3D, Multimedia, PDF, Designer tools, and other
unused components, which was the main cause of the ~647 MB distribution.
"""
from PyInstaller.utils.hooks import collect_submodules

# Mutagen discovers format handlers dynamically through mutagen.File().
# Include its Python submodules, but do not collect the package as data and
# binaries because it is a pure-Python dependency.
hiddenimports = collect_submodules("mutagen")

# Keep application resources inside PyInstaller's _internal directory.
datas = [("resources", "resources")]

# Explicitly exclude large Qt modules that Playlist Fixer does not import.
# These exclusions are defensive; the normal PyInstaller hooks should not
# collect them after collect_all("PySide6") has been removed.
excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

# Some PyInstaller hooks collect optional packages merely because they happen to
# be installed on the build computer. Prune only components Playlist Fixer never
# imports so a full developer environment produces the same minimal portable
# layout as the documented clean build environment.
unused_artifact_prefixes = (
    "PIL/",
    "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
)
unused_qt_binaries = {
    "PySide6/Qt6OpenGL.dll",
    "PySide6/Qt6Pdf.dll",
    "PySide6/Qt6Qml.dll",
    "PySide6/Qt6QmlMeta.dll",
    "PySide6/Qt6QmlModels.dll",
    "PySide6/Qt6QmlWorkerScript.dll",
    "PySide6/Qt6Quick.dll",
    "PySide6/Qt6VirtualKeyboard.dll",
}


def keep_artifact(entry):
    destination = str(entry[0]).replace("\\", "/")
    return (
        destination not in unused_qt_binaries
        and not destination.startswith(unused_artifact_prefixes)
    )


a.pure = [entry for entry in a.pure if not str(entry[0]).startswith("PIL")]
a.binaries = [entry for entry in a.binaries if keep_artifact(entry)]
a.datas = [entry for entry in a.datas if keep_artifact(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlaylistFixer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PlaylistFixer",
)
