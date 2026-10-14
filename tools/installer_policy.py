"""One upgrade identity and non-destructive setup policy for every AURA release."""
import re,json
from pathlib import Path,PurePosixPath
APP_MUTEX='AURA.Photo.Standalone.Running'

# Separate AURA Photo identity. Never use the original AURA identity here.
APP_GUID='C8F2915C-BBA6-4AB2-BFE5-6377282D28F4'
APP_ID='{{'+APP_GUID+'}'
DEFAULT_DIR=r'{localappdata}\Programs\AURA Photo'
BEGIN='// BEGIN AURA OVERLAY UPGRADE POLICY'
END='// END AURA OVERLAY UPGRADE POLICY'
PROTECTED=(r'\acceleration.json',r'\preferences.json','*.beauty','*.portrait.json',r'\.aura-data\*','*.aura-style.json',r'\.aura-photo-data\*')
DIRECTIVES=dict(AppId=APP_ID,DefaultDirName=DEFAULT_DIR,PrivilegesRequired='lowest',
    UsePreviousAppDir='yes',UsePreviousGroup='yes',UsePreviousTasks='yes',DisableDirPage='auto',
    UninstallLogMode='append',Uninstallable='yes',CreateUninstallRegKey='yes',
    AppMutex=APP_MUTEX,SetupMutex='AURA.Setup.'+APP_GUID,CloseApplications='no',
    CloseApplicationsFilter='*.exe,*.dll,*.pyd',RestartApplications='no')

def _retirement_code(retired_assets=None):
    if retired_assets is None:
        path=Path(__file__).resolve().parent/'installer/retired-relight-assets.json'
        retired_assets=json.loads(path.read_text(encoding='utf8')) if path.exists() else []
    calls=[]
    for item in retired_assets:
        name=item['path'];p=PurePosixPath(name);digest=item['sha256']
        if p.is_absolute() or '..' in p.parts or not name.startswith(('models/relight/normals/','models/relight/depth-small/')) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise ValueError('Retired light asset must be an exact known old model file.')
        calls.append("    AURARetireVerifiedModel('"+name.replace('/',chr(92))+"', '"+digest+"');")
    return r'''
function AURAFileAttributes(FileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function AURAPlainModelPath(FileName: String): Boolean;
var
  Current, Root, Parent: String;
  Attributes: LongWord;
begin
  Result := False;
  Root := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  Current := FileName;
  while Length(Current) >= Length(Root) do begin
    Attributes := AURAFileAttributes(Current);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then Exit;
    if CompareText(Current, Root) = 0 then begin Result := True; Exit; end;
    Parent := ExtractFileDir(Current);
    if Parent = Current then Exit;
    Current := Parent;
  end;
end;

procedure AURARetireVerifiedModel(RelativeName, ExpectedHash: String);
var
  FileName: String;
begin
  FileName := AddBackslash(ExpandConstant('{app}')) + RelativeName;
  if not FileExists(FileName) or not AURAPlainModelPath(FileName) then Exit;
  try
    if CompareText(GetSHA256OfFile(FileName), ExpectedHash) = 0 then begin
      if DeleteFile(FileName) then Log('Removed verified obsolete AURA file: ' + RelativeName)
      else Log('Kept locked obsolete file: ' + RelativeName);
    end else Log('Preserved modified file: ' + RelativeName);
  except
    Log('Kept model which could not be verified: ' + RelativeName);
  end;
end;

<event('CurStepChanged')>
procedure AURARetireOldLightAssets(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
CALLS
  end;
end;
'''.replace('CALLS','\n'.join(calls))

def _runtime_retirement_code():
    return r'''
<event('CurStepChanged')>
procedure AURARetireOldRuntimeFiles(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
  I: Integer;
  Name, Hash, LowerName: String;
begin
  if CurStep <> ssPostInstall then Exit;
  ExtractTemporaryFile('aura-retired-runtime.tsv');
  if not LoadStringsFromFile(ExpandConstant('{tmp}\aura-retired-runtime.tsv'), Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    if (Length(Lines[I]) > 65) and (Copy(Lines[I], 65, 1) = '|') then begin
      Hash := Copy(Lines[I], 1, 64);
      Name := Copy(Lines[I], 66, Length(Lines[I]));
      LowerName := Lowercase(Name);
      if (Pos('..', Name) = 0) and (Pos(':', Name) = 0) and (Pos('/', Name) = 0) and
        ((Pos('runtime\lib\', LowerName) = 1) or
         (Pos('runtime\gpu-site-packages\', LowerName) = 1) or
         (Pos('gpu-render-deps-cuda130\nvidia\', LowerName) = 1)) then
        AURARetireVerifiedModel(Name, Hash);
    end;
  end;
end;
'''


def _code(guid=APP_GUID,retired_assets=None):
    return r'''
// BEGIN AURA OVERLAY UPGRADE POLICY
const
  AURAUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{GUID}_is1';
var
  AURAPreviousDirectory: String;

function AURAFindPreviousDirectory: String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, AURAUninstallKey, 'Inno Setup: App Path', Result) then
    RegQueryStringValue(HKCU, AURAUninstallKey, 'InstallLocation', Result);
end;

function AURAUpdateInstall: Boolean;
begin
  Result := ExpandConstant('{param:AURAUPDATE|0}') = '1';
end;

<event('InitializeWizard')>
procedure AURAPinPreviousDirectory;
begin
  AURAPreviousDirectory := AURAFindPreviousDirectory;
  if AURAPreviousDirectory <> '' then begin
    WizardForm.DirEdit.Text := AURAPreviousDirectory;
    WizardForm.DirEdit.Enabled := False;
    WizardForm.DirBrowseButton.Enabled := False;
    Log('AURA upgrade target pinned to previous installation: ' + AURAPreviousDirectory);
  end;
end;

<event('PrepareToInstall')>
function AURAEnsureOverlay(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if AURAPreviousDirectory <> '' then
    WizardForm.DirEdit.Text := AURAPreviousDirectory;
end;
RETIREMENT
// END AURA OVERLAY UPGRADE POLICY
'''.replace('{GUID}','{'+guid+'}').replace('RETIREMENT',_retirement_code(retired_assets)+_runtime_retirement_code())

def apply_installer_policy(text,retired_assets=None,runtime_manifest=None):
    """Normalize legacy templates, preserving other sections and event handlers."""
    if BEGIN in text:text=text[:text.index(BEGIN)]+text[text.index(END)+len(END):]
    parts=re.split(r'(?m)^(\[[A-Za-z]+\])[ \t]*$',text.replace('\r\n','\n'))
    sections={parts[i].lower():i for i in range(1,len(parts),2)}
    if '[setup]' not in sections or '[files]' not in sections:raise ValueError('AURA installer requires Setup and Files sections.')
    for name in ('[installdelete]','[uninstalldelete]'):
        if name in sections and any(s.strip() and not s.lstrip().startswith(';') for s in parts[sections[name]+1].splitlines()):
            raise ValueError('AURA upgrade may not delete installation folders or user files.')
    i=sections['[setup]']+1;body=parts[i]
    for key,value in DIRECTIVES.items():
        body=re.sub(r'(?mi)^'+key+r'\s*=.*\n?','',body)
        body=body.rstrip()+'\n'+key+'='+value+'\n'
    # Keep all releases in the original per-user installation context.
    body=re.sub(r'(?mi)^PrivilegesRequiredOverridesAllowed\s*=.*\n?','',body)
    parts[i]=body+'\n'
    i=sections['[files]']+1;lines=[]
    for line in parts[i].splitlines():
        if 'DestName: "aura-retired-runtime.tsv"' in line:continue
        if line.lstrip().lower().startswith('source:'):
            match=re.search(r'(?i)\bExcludes:\s*"([^"]*)"',line)
            patterns=list(PROTECTED)
            if match:
                patterns=list(dict.fromkeys(match[1].split(',')+patterns))
                line=line[:match.start()]+'Excludes: "'+','.join(patterns)+'"'+line[match.end():]
            else:line+='; Excludes: "'+','.join(patterns)+'"'
        lines.append(line)
    runtime_manifest=Path(runtime_manifest or Path(__file__).resolve().parent/'installer/retired-runtime-files.tsv').resolve()
    if not runtime_manifest.is_relative_to(Path(__file__).resolve().parents[1]):raise ValueError('Retirement manifest must stay in project.')
    def reason(name):return False
    for row in runtime_manifest.read_text(encoding='utf8').splitlines():
        digest,sep,name=row.partition('|');p=PurePosixPath(name.replace(chr(92),'/'))
        if not sep or not re.fullmatch('[a-f0-9]{64}',digest) or p.is_absolute() or '..' in p.parts or ':' in name or not reason(p.as_posix()):
            raise ValueError('Invalid deployment retirement entry: '+row)
    while lines and not lines[-1].strip():lines.pop()
    lines.append('Source: "'+str(runtime_manifest)+'"; DestDir: "{tmp}"; DestName: "aura-retired-runtime.tsv"; Flags: dontcopy')
    parts[i]='\n'+'\n'.join(lines).strip('\n')+'\n\n'
    if '[code]' not in sections:parts+=['[Code]','\n'+_code(retired_assets=retired_assets)]
    else:parts[sections['[code]']+1]=parts[sections['[code]']+1].rstrip()+'\n\n'+_code(retired_assets=retired_assets).strip()+'\n'
    return ''.join(parts).rstrip()+'\n'

def write_installer_script(path,text):
    path=Path(path).resolve();root=Path(__file__).resolve().parents[1]
    if not path.is_relative_to(root):raise ValueError('New installer artifacts must stay in the project folder.')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(apply_installer_policy(text),encoding='utf8')
    return path

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Apply the shared AURA overlay-upgrade policy.')
    parser.add_argument('script',type=Path);args=parser.parse_args()
    write_installer_script(args.script,args.script.read_text(encoding='utf8'))
