import os,sys
if __name__ == '__main__' and '--mcp' in sys.argv:
    from aura_mcp import main
    main()
    raise SystemExit(0)
os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
from dpi_support import enable_dpi
enable_dpi()
from i18n import install as install_localization
install_localization()
from app_v3 import App, main, ROOT
if __name__ == "__main__": main()
