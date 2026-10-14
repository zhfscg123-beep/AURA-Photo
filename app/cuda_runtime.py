"""One bundled CUDA DLL set for Torch, ONNX Runtime and CuPy, including CPU AI mode."""
import ctypes
import os
from pathlib import Path

# Validated with the current offline cu130 wheel; do not deduplicate by filename alone.
SHARED_DLLS = (
    'cublas64_13.dll', 'cublasLt64_13.dll', 'cudart64_13.dll',
    'cufft64_12.dll', 'cufftw64_12.dll', 'curand64_10.dll',
    'cusolver64_12.dll', 'cusolverMg64_12.dll', 'cusparse64_12.dll',
    'nvJitLink_130_0.dll', 'nvrtc-builtins64_130.dll',
    'nvrtc64_130_0.alt.dll', 'nvrtc64_130_0.dll',
)
PATTERNS = ('nvrtc-builtins*.dll', 'nvrtc64*.dll', 'cudart64*.dll',
            'cublasLt64*.dll', 'cublas64*.dll', 'nvJitLink*.dll',
            'cusparse64*.dll', 'cusolver64*.dll', 'cufft64*.dll')


def shared_directory(root):
    root = Path(root)
    for relative in ('runtime/gpu-site-packages/torch/lib', '.venv-gpu/Lib/site-packages/torch/lib'):
        folder = root / relative
        if folder.is_dir():
            missing = [name for name in SHARED_DLLS if not (folder / name).is_file()]
            if missing:
                raise RuntimeError('共享 CUDA 运行库不完整，请重新安装完整包：' + ', '.join(missing))
            return folder
    return None


def preload(root, deps, handles):
    """Retain DLL directory handles without importing GPU Torch into a CPU process."""
    shared = shared_directory(root)
    bins = sorted({p.parent for p in (Path(deps) / 'nvidia').rglob('*.dll')})
    if shared is not None:
        bins = [shared] + [p for p in bins if p != shared]
    os.environ['PATH'] = os.pathsep.join(map(str, bins)) + os.pathsep + os.environ.get('PATH', '')
    if os.name != 'nt':
        return
    handles.extend(os.add_dll_directory(str(p)) for p in bins)
    api = ctypes.WinDLL('kernel32')
    api.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    api.GetModuleHandleW.restype = ctypes.c_void_p
    for pattern in PATTERNS:
        paths = list(shared.glob(pattern)) if shared else []
        names = {p.name.casefold() for p in paths}
        paths.extend(p for p in (Path(deps) / 'nvidia').rglob(pattern) if p.name.casefold() not in names)
        for path in paths:
            if not api.GetModuleHandleW(path.name):
                handles.append(ctypes.WinDLL(str(path)))
