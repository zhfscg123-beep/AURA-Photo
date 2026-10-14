"""Relocatable GPU launcher with retained CPU libraries as fallback."""
import os,sys,subprocess,traceback,ctypes
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ['AURA_DATA_DIR']=str(ROOT/'.aura-photo-data')
os.environ['AURA_MCP_ENDPOINT_FILE']=str(ROOT/'.aura-photo-data/mcp/endpoint.json')
os.environ['AURA_UPDATE_CHECK']='0'
data=ROOT/'.aura-photo-data';(data/'temp').mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=str(data/'temp');os.environ['TMP']=str(data/'temp')
if sys.stdout is None or sys.stderr is None:
    log=(data/'startup.log').open('a',encoding='utf8',buffering=1)
    if sys.stdout is None:sys.stdout=log
    if sys.stderr is None:sys.stderr=log
os.environ.setdefault('BEAUTY_AI_DEVICE','auto')
os.environ.pop('SD_ENABLE_ASIO',None)
from i18n import install as install_localization
install_localization()

os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
from dpi_support import enable_dpi
enable_dpi()
def launch():
    if '--mcp' in sys.argv:
        from aura_mcp import main
        main();return
    gpu=ROOT/'runtime/gpu-site-packages'
    if gpu.is_dir() and os.environ.get('BEAUTY_PORTABLE_CPU')!='1':sys.path.insert(0,str(gpu))
    try:
        import torch,onnxruntime
        from app import main
    except (ImportError,OSError,RuntimeError):
        (ROOT/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
        if os.environ.get('BEAUTY_PORTABLE_CPU')!='1':
            env=os.environ.copy();env['BEAUTY_PORTABLE_CPU']='1';env['BEAUTY_AI_DEVICE']='cpu';env['AURA_RENDER_BACKEND']='cpu'
            subprocess.Popen([sys.executable,str(ROOT/'portable_bootstrap.py'),*sys.argv[1:]],cwd=ROOT,env=env,creationflags=subprocess.CREATE_NO_WINDOW);return
        from i18n import tr
        ctypes.windll.user32.MessageBoxW(None,tr('启动失败，详细原因见程序目录 startup-error.log。'),'AURA Photo',0x10);raise SystemExit(1)
    if '--self-test' in sys.argv:
        import portable_self_test
        portable_self_test.main(sys.argv);return
    if torch.cuda.is_available() and os.environ.get('AURA_RENDER_BACKEND','cuda')!='cpu':
        from cuda_headers import prepare_interactive
        prepare_interactive()
    main()
if __name__=='__main__':launch()
