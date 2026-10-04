"""One-file console maintenance executable. Only allowlisted resource data."""
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct

root = Path(SPECPATH).parent
maintenance = root / 'scripts/maintenance'
provenance = Path(os.environ['SEEDLAB_IMPORTER_PROVENANCE'])
data = collect_data_files('tzdata') + collect_data_files('pypinyin')
data += [(str(maintenance / 'legacy_schema_contract.json'), '.'), (str(provenance), '.')]
analysis = Analysis([str(maintenance / 'legacy_production_import.py')],
    pathex=[str(maintenance), str(root / 'backend'), str(root)],
    binaries=[], datas=data, hiddenimports=['sqlalchemy.dialects.sqlite'],
    excludes=['PySide6', 'numpy', 'pandas', 'matplotlib', 'pytest', 'IPython', 'tkinter', 'uvicorn'],
    noarchive=False)
for name, path, kind in analysis.datas:
    candidate = Path(path)
    forbidden_file = candidate.suffix.lower() in {'.db', '.xlsx', '.xls', '.csv', '.zip'}
    if candidate.name == 'base_library.zip' and candidate.is_relative_to(root / 'build'):
        forbidden_file = False  # PyInstaller-generated standard-library resource.
    if forbidden_file or any(
        part.lower() in {'.git', 'seedlabdata', 'tests', 'secrets'} for part in candidate.parts) or candidate.name == '.env':
        raise RuntimeError('Sensitive or test data refused: ' + str(candidate))
pyz = PYZ(analysis.pure)
version = VSVersionInfo(ffi=FixedFileInfo(filevers=(1,0,0,0), prodvers=(1,0,0,0),
    mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[
    StringFileInfo([StringTable('080404b0', [StringStruct('ProductName','SeedLabLegacyImport'),
        StringStruct('ProductVersion','1.0.0'), StringStruct('FileVersion','1.0.0'),
        StringStruct('FileDescription','SeedLab 历史数据受控导入维护工具')])])])
exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='SeedLabLegacyImport-v1.0.0', debug=False, strip=False, upx=False,
    console=True, version=version, icon=str(root / 'control_center/assets/SeedLab.ico'))
