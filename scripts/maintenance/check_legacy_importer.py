"""Inspect the actual PyInstaller archive; never extract user data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from PyInstaller.archive.readers import CArchiveReader


def inspect(exe, commit):
    archive = CArchiveReader(str(exe))
    forbidden = re.compile(r"(?:^|[/\\])(?:\.git|seedlabdata|tests|secrets)(?:[/\\]|$)|(?:\.db(?:-(?:wal|shm|journal))?|\.xlsx?|\.csv|\.env)$", re.I)
    violations = [name for name in archive.toc if forbidden.search(name)]
    pyz = archive.open_embedded_archive('PYZ.pyz')
    violations += [name for name in pyz.toc if re.search(r'(?:^|\.)(tests|pytest)(?:\.|$)', name)]
    assert not violations, f'Forbidden packaged entries: {violations}'
    provenance = json.loads(archive.extract('legacy_build_provenance.json'))
    assert provenance['git_commit'] == commit and provenance['importer_version'] == '1.0.0'
    assert 'legacy_schema_contract.json' in archive.toc
    assert 'legacy_import_core' in pyz.toc
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(exe.resolve()), 'size':exe.stat().st_size, 'sha256':digest, 'git_commit':commit,
            'importer_version':'1.0.0', 'target_compatibility':'SeedLab 0.5.1 / d2e7a46b910c',
            'archive_entries':len(archive.toc), 'module_entries':len(pyz.toc), 'forbidden_entries':violations}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=inspect(args.exe,args.commit)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
