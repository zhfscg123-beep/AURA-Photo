"""Local source preflight. This does not publish or grant a project license."""
from pathlib import Path
import ast,re,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
forbidden={'.exe','.dll','.pyd','.pyc','.pth','.pt','.onnx','.task','.tflite','.bin','.arw','.dcp','.beauty','.whl','.zip'}

def sensitive_text_kinds(value):
    """Return categories only; never print a suspected credential's value."""
    patterns={
        'credential':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{30,}|hf_[A-Za-z0-9]{25,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})\b',
        'private_key':r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----',
        'local_user_path':r'(?i)[A-Z]:[/\\]+(?:Users|Documents and Settings)[/\\]+[A-Za-z0-9_ .-]+[/\\]',
        'unix_user_path':r'/(?:Users|home)/[A-Za-z0-9_.-]+/',
        'absolute_photo_path':r'(?i)\b[A-Z]:[/\\][^\r\n\t"<>|]*\.(?:arw|nef|cr2|cr3|dng|raf|jpg|jpeg|png|tif|tiff|beauty)\b',
        'url_embedded_password':r'(?i)\b(?:https?|ftp|socks5?)://[^\s:/@"\']+:[^\s/@"\']+@',
        'signed_url':r'(?i)[?&](?:X-Amz-(?:Credential|Signature)|X-Goog-(?:Credential|Signature)|access_token|api_key)=[A-Za-z0-9%_./+-]{8,}',
    }
    return [kind for kind,pattern in patterns.items() if re.search(pattern,value)]
def main():
    files=[];issues=[]
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if any(part in ('work','dist','.git','__pycache__') for part in rel.parts):continue
        if not p.is_file():continue
        if any(part in ('.aura-photo-data','.aura-data','.ssh','.aws','recovery','session-temp') for part in rel.parts) or p.name in ('preferences.json','acceleration.json','endpoint.json','credentials') or p.name=='.env' or p.name.startswith('.env.') or p.suffix.lower() in ('.log','.db','.sqlite','.sqlite3','.pem','.key','.pfx','.p12'):
            issues.append(str(rel)+' private state or credential file')
        if p.is_symlink() or p.suffix.lower() in forbidden or p.stat().st_size>=100*1024**2:issues.append(str(rel))
        if p.suffix=='.py':ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(rel))
        try:value=p.read_text(encoding='utf-8-sig')
        except UnicodeError:value=None
        if value is not None:
            for kind in sensitive_text_kinds(value):issues.append(str(rel)+' '+kind)
        files.append(p)
    assert not issues,issues
    manifest=json.loads((ROOT/'app/models-manifest.json').read_text(encoding='utf8'))
    for item in manifest['active_models']:assert not (ROOT/'app/models'/item['file']).exists()
    for item in manifest['excluded_weights']:assert not (ROOT/'app/models'/item).exists()
    print(json.dumps(dict(files=len(files),bytes=sum(p.stat().st_size for p in files),max_file_bytes=max(p.stat().st_size for p in files),syntax_passed=True,no_runtime_or_weights=True,no_detected_credentials=True,project_license_pending=not (ROOT/'LICENSE').exists())))
if __name__=='__main__':main()
