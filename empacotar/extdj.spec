# Receita do PyInstaller: gera build/dist/Extended DJ/Extended DJ.exe (pasta, não arquivo único:
# com o PyTorch dentro, um .exe único levaria quase um minuto descompactando a cada abertura).
# Rode pelo empacotar/construir.bat.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent
BUILD = RAIZ / "build"

datas = [
    (str(RAIZ / "src/extdj/app/ui"), "extdj/app/ui"),
    (str(BUILD / "modelos"), "modelos"),
    (str(BUILD / "ffmpeg"), "ffmpeg"),
]
datas += collect_data_files("demucs")
datas += collect_data_files("librosa", includes=["**/*.pyi", "**/*.txt", "**/*.json", "**/*.csv"])
datas += collect_data_files("lazy_loader")
datas += collect_data_files("webview")

hiddenimports = (
    collect_submodules("demucs")
    + collect_submodules("beat_this")
    + collect_submodules("extdj")
    + ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]
)

a = Analysis(
    [str(RAIZ / "empacotar/iniciar.py")],
    pathex=[str(RAIZ / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "tensorboard",
              "torch.utils.tensorboard", "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    # o librosa usa numba com cache, que precisa do .py ao lado; o torch lê o próprio código-fonte
    module_collection_mode={"librosa": "pyz+py", "numba": "pyz+py", "torch": "pyz+py"},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Extended DJ",
    icon=str(RAIZ / "empacotar/icone.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Extended DJ")
