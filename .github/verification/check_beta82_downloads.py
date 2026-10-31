"""Read-only GitHub Actions verification of the exact standalone user download."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(r'C:\TGC-Designer-Tools')
DOWNLOADS = Path.home() / 'Downloads'
CMD = 'UPDATE_TGC_BETA8_2.cmd'
BASE = '67980485fd0639e3458382487ed1fee831de078d'
REPO = 'malifica/TGC-Designer-Tools'
PLAN = Path('.github/verification/beta82-downloads-input.json')
INPUT = json.loads(PLAN.read_text(encoding='utf-8'))
TARGET = INPUT['source_sha']
SENTINELS = {'dist/tgc_gui_2k25_beta8_1.exe': b'prior EXE sentinel; not executable',
             'dist/tgc_gui_2k25_beta8_2.exe': b'untouched EXE sentinel; not executable',
             'custom-course/hand-edited-mask.png': b'private project sentinel',
             'README.md': b'unrelated edited local documentation\n'}


def require(condition, error):
    if not condition: raise ValueError(error)


def sha(b): return hashlib.sha256(b).hexdigest()


def git(*args, data=None):
    return subprocess.check_output(['git',*args], input=data)


def tree(ref):
    require(re.fullmatch('[a-f0-9]{40}',ref) and git('rev-parse',ref+'^{commit}').decode().strip()==ref,'Unexpected Git commit')
    entries = {}
    for rec in git('ls-tree','-rz','--full-tree',ref).split(b'\0'):
        if not rec: continue
        attrs,name = rec.split(b'\t',1); mode,kind,digest = attrs.decode().split()
        key = name.decode()
        require(mode in ('100644','100755') and kind=='blob' and all(k not in ('.','..','.git','') for k in key.split('/')) and not re.search(r'[:\\]',key), 'Unsafe source path')
        entries[key]=digest
    return entries


def contents(entries):
    digests = sorted(set(entries.values()))
    inp = ('\n'.join(digests)+'\n').encode()
    out = io.BytesIO(git('cat-file','--batch',data=inp))
    blobs = {}
    for digest in digests:
        obj,kind,size=out.readline().strip().split()
        require(obj.decode()==digest and kind==b'blob','Unexpected Git blob')
        raw=out.read(int(size))
        require(len(raw)==int(size) and out.read(1)==b'\n','Incomplete Git blob')
        blobs[digest]=raw
    return {k:blobs[d] for k,d in entries.items()}


def put(root, name, raw):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)


def read_cmd():
    raw = bytearray()
    for c in INPUT['chunks']:
        digest=c['git_blob_sha']
        require(re.fullmatch('[a-f0-9]{40}',digest),'Invalid Git blob ID')
        req=urllib.request.Request('https://api.github.com/repos/'+REPO+'/git/blobs/'+digest,headers={
            'Accept':'application/vnd.github+json','Authorization':'Bearer '+os.environ['GH_TOKEN'],
            'X-GitHub-Api-Version':'2022-11-28','User-Agent':'TGC-Downloads-CMD-check'})
        with urllib.request.urlopen(req,timeout=60) as f: obj=json.load(f)
        require(obj['encoding']=='base64','Unexpected blob encoding')
        b=base64.b64decode(obj['content'])
        require(obj['sha']==digest and hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==digest,'Git blob differs')
        require(len(b)==c['bytes'] and sha(b)==c['sha256'],'Transport chunk differs')
        raw.extend(b)
    require(len(raw)==INPUT['cmd_bytes'] and sha(raw)==INPUT['cmd_sha256'],'Downloaded CMD differs')
    return raw


def stage():
    require(not ROOT.exists(),'Refusing to overwrite an existing project folder')
    require(not (DOWNLOADS/CMD).exists(),'Refusing to replace a Downloads file')
    base=contents(tree(BASE));tree(TARGET)
    ROOT.mkdir();DOWNLOADS.mkdir(exist_ok=True)
    for name,b in {**base,**SENTINELS}.items(): put(ROOT,name,b)
    subprocess.run([sys.executable,'-m','venv',str(ROOT/'.venv_local_osm')],check=True)
    raw=read_cmd();put(DOWNLOADS,CMD,raw)
    print('Staged the original download: %s bytes, SHA-256 %s' % (len(raw),sha(raw)))


def run_cmd(body,cwd,expected=0):
    # /s strips one outer quote pair; the body itself is exactly ordinary CMD
    # syntax, including the quoted path when invoked from outside Downloads.
    command='cmd.exe /d /v:off /s /c "'+body+'"'
    proc=subprocess.run(command,cwd=cwd,text=True,encoding='utf-8',errors='replace',
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=150)
    require(proc.returncode==expected,'CMD returned %d (expected %d):\n%s'%(proc.returncode,expected,proc.stdout[-4000:]))
    return proc.stdout


def snapshot(folder):
    return {p.relative_to(folder).as_posix():sha(p.read_bytes()) for p in folder.rglob('*')
            if p.is_file() and '.venv_local_osm' not in p.relative_to(folder).parts}


def exercise():
    base=contents(tree(BASE));target=contents(tree(TARGET))
    expected={n for n in json.loads(base['BETA8_1_UPLOAD_MANIFEST.json'])['files'] if not n.startswith('dist/')}
    require(len(expected)==141,'Unexpected baseline manifest')
    expected.update(n for n,b in target.items() if base.get(n)!=b and '/' not in n and
                    (n.endswith(('.py','.bat','.spec')) or n=='RELEASE_NOTES_v0.5.0-2k25-beta8.2.md'))
    require({'BUILD_TGC_2K25_BETA8_2.py','BUILD_TGC_2K25_BETA8_2.bat','COLLECT_BETA8_2_FOR_PUBLICATION.py',
             'VERIFY_BETA8_2_PARKING.py','tgc_gui.py','OSMTGC.py'} <= expected,'Missing Beta 8.2 paths')
    require(sha((DOWNLOADS/CMD).read_bytes())==INPUT['cmd_sha256'],'Downloads file changed')
    elsewhere=Path(os.environ['RUNNER_TEMP'])
    before=snapshot(ROOT)
    interpreter=ROOT/'.venv_local_osm/Scripts/python.exe'
    original_python=sha(interpreter.read_bytes())
    cmd_ref='"%USERPROFILE%\\Downloads\\'+CMD+'"'
    report=run_cmd(cmd_ref+' --check-only',elsewhere)
    require('Planned updates:' in report and TARGET in report and snapshot(ROOT)==before,'--check-only changed project or used wrong target')
    # Conflict fixture deliberately has no project interpreter. A real build
    # cannot start even if some other guard fails. Expect source conflict first.
    conflict=elsewhere/'Conflicting Beta 8.1'
    conflict.mkdir()
    for n,b in base.items(): put(conflict,n,b)
    put(conflict,'OSMTGC.py',base['OSMTGC.py']+b'\n# unknown local change\n')
    old=snapshot(conflict)
    report=run_cmd(cmd_ref+' --root "'+str(conflict)+'" --build',elsewhere,1)
    require('OSMTGC.py' in report and 'STOPPED:' in report and 'READY FOR ONE WINDOWS BUILD' not in report and snapshot(conflict)==old,'Conflicting --build did not stop before source mutation')
    # Normal command: change to Downloads, run the shipped CMD directly.
    report=run_cmd('cd /d "%USERPROFILE%\\Downloads" && '+CMD,elsewhere)
    require(TARGET in report and 'READY FOR ONE WINDOWS BUILD' in report and 'No Windows build was started.' in report,'Default updater did not complete without building')
    for n in expected: require((ROOT/n).read_bytes()==target[n],'Patched source differs from commit: '+n)
    for n,b in SENTINELS.items(): require((ROOT/n).read_bytes()==b,'Sentinel changed: '+n)
    require(sha(interpreter.read_bytes())==original_python,'Project Python changed')
    backups=list((ROOT/'_source_update_backups').glob('Beta8_2_*'))
    require(len(backups)==1,'Expected one verified update backup')
    old=snapshot(ROOT)
    special=DOWNLOADS/'Space & exclamation!';special.mkdir()
    shutil.copyfile(DOWNLOADS/CMD,special/CMD)
    report=run_cmd('"%USERPROFILE%\\Downloads\\Space & exclamation!\\'+CMD+'"',elsewhere)
    require(TARGET in report and snapshot(ROOT)==old,'Repeated run from a quoted special path changed the project')
    print('PASS: real Windows CMD, Downloads & external working directory, spaces/ampersand/exclamation, '
          'check-only, source-conflict --build guard, default apply, backup, idempotence, both EXE sentinels and existing venv preserved.')
    print('PASS: %d source/build/support files match exact Git commit %s.'%(len(expected),TARGET))


if __name__=='__main__':
    require(os.name=='nt' and os.environ.get('GITHUB_REPOSITORY')==REPO and
            os.environ.get('GITHUB_REF')=='refs/heads/checks/beta82-downloads-cmd','Wrong Windows verification environment')
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['stage','exercise'])
    (stage if parser.parse_args().phase=='stage' else exercise)()
