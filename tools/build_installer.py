from pathlib import Path
import os,json,hashlib,subprocess,sys
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--app-dir',type=Path,required=True)
parser.add_argument('--compiler',type=Path,required=True)
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
APP=args.app_dir.resolve()
assert APP.is_relative_to(ROOT/'work'), 'Build only from a private work/ staging directory'
import installer_policy as policy
OUT=ROOT/'dist/0.2.0';OUT.mkdir(parents=True,exist_ok=True)
(ROOT/'work/build-logs').mkdir(parents=True,exist_ok=True)
excluded_dirs={'.aura-photo-data','.aura-data','__pycache__','.git'}
excluded_names={'startup-error.log','install-self-test.json','distribution-manifest.json','installed-language.json'}
files=[]
for directory,dirs,names in os.walk(APP):
    dirs[:]=[d for d in dirs if d not in excluded_dirs]
    for name in names:
        p=Path(directory)/name
        if name in excluded_names or p.suffix.lower() in ('.pyc','.log'):continue
        files.append(p)
files.sort();manifest=[]
for p in files:
    rel=p.relative_to(APP).as_posix();h=hashlib.sha256()
    assert not rel.lower().endswith(('.arw','.dcp','.beauty'))
    assert not any(x in p.name.lower() for x in ('ffmpeg','nvperf_host.dll','asio.dll'))
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    manifest.append(dict(file=rel,bytes=p.stat().st_size,sha256=h.hexdigest()))
(APP/'distribution-manifest.json').write_text(json.dumps(dict(version='0.2.0',edition='GPU + CPU, Chinese + English',files=manifest),ensure_ascii=False,indent=2),encoding='utf8')
files.append(APP/'distribution-manifest.json')
print('Verified payload:',len(files),'files',flush=True)
entries=[]
for p in files:
    relative=p.relative_to(APP);dest='{app}'+('\\'+str(relative.parent) if relative.parent!=Path('.') else '')
    entries.append('Source: "'+str(p)+'"; DestDir: "'+dest+'"; Flags: ignoreversion')
script=r'''[Setup]
AppName=AURA Photo
AppVersion=0.2.0
AppPublisher=zhfscg123-beep
LicenseFile=APP\LICENSE-AURA.txt
DefaultGroupName=AURA Photo
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir=OUTPUT
OutputBaseFilename=AURA-Photo-0.2.0-Windows-GPU-Setup
SetupIconFile=APP\assets\aura.ico
UninstallDisplayIcon={app}\AURA Photo.exe
WizardStyle=modern
Compression=zip/1
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=1500000000
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage
[Languages]
Name: "chinesesimp"; MessagesFile: "ROOT\tools\installer\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[CustomMessages]
english.DesktopShortcut=Create a desktop shortcut
chinesesimp.DesktopShortcut=创建桌面快捷方式
english.ClosePhoto=Please save your edits and close AURA Photo before continuing.
chinesesimp.ClosePhoto=请先保存编辑并退出 AURA Photo，然后继续安装。
english.WrongEdition=Choose a separate folder for AURA Photo. This folder contains the original AURA edition.
chinesesimp.WrongEdition=此目录包含原版 AURA，请为独立版选择其他目录。
[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked
[Files]
ENTRIES
[Icons]
Name: "{group}\AURA Photo"; Filename: "{app}\AURA Photo.exe"
Name: "{autodesktop}\AURA Photo"; Filename: "{app}\AURA Photo.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\AURA Photo.exe"; Description: "{cm:LaunchProgram,AURA Photo}"; Flags: nowait postinstall skipifsilent
[Code]
<event('CurStepChanged')>
procedure PhotoLanguageDefault(CurStep: TSetupStep);
var Value: String;
begin
  if CurStep = ssPostInstall then begin
    if ActiveLanguage = 'english' then Value := '{"language":"en_US"}'
    else Value := '{"language":"zh_CN"}';
    if not SaveStringToFile(ExpandConstant('{app}\installed-language.json'), Value, False) then
      RaiseException('Could not save application language');
  end;
end;

<event('PrepareToInstall')>
function PhotoCheckTarget(var NeedsRestart: Boolean): String;
var Original, Target: String; Existing: AnsiString;
begin
  Result := '';
  if CheckForMutexes('AURA.Photo.Standalone.Running') then begin
    Result := CustomMessage('ClosePhoto'); Exit;
  end;
  Target := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{69C8D36D-01CD-48D1-83EB-56828F1C82DD}_is1', 'Inno Setup: App Path', Original) then
    if CompareText(RemoveBackslashUnlessRoot(Original), Target) = 0 then begin
      Result := CustomMessage('WrongEdition'); Exit;
    end;
  if FileExists(Target+'\app_mutex.py') then
    if LoadStringFromFile(Target+'\app_mutex.py', Existing) then
      if Pos('AURA.Photo.Standalone.Running', Existing) = 0 then
        Result := CustomMessage('WrongEdition');
end;
'''.replace('OUTPUT',str(OUT)).replace('APP\\',str(APP)+'\\').replace('ROOT\\',str(ROOT)+'\\').replace('ENTRIES','\n'.join(entries))
path=policy.write_installer_script(ROOT/'work/AURA-Photo-0.2.0.iss',script)
assert 'AppId={{'+policy.APP_GUID+'}' in path.read_text(encoding='utf8')
compiler=args.compiler.resolve()
with (ROOT/'work/build-logs/compile-installer.log').open('w',encoding='utf8') as log:
    result=subprocess.run([str(compiler),'/Qp',str(path)],stdout=log,stderr=subprocess.STDOUT)
print('Installer compiler exit:',result.returncode,flush=True)
raise SystemExit(result.returncode)
