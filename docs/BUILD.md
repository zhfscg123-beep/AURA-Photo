# Windows 构建与验证

本快照包含 AURA 应用及其第三方适配源码。最直接的开发路径是复用 **同版本完整安装包中的已验证依赖**；安装包附模型、CPU/GPU 运行库、RawTherapee、ExifTool 及对应源码和许可材料。开发环境通过完整安装目录准备。

## 1. 准备工作目录

使用 Windows x64、Python 3.12，先安装 AURA Photo 0.2.0。关闭应用后执行：

```powershell
python tools/create_development.py --base-dir "C:\Path\To\AURA Photo"
```

输出在 `work/AURA Photo`。目录必须是新目录；工具先核对分发清单和 SHA-256，再复制分发文件和当前仓库源码。用户数据、下载来源元数据不复制。约需 6 GB 磁盘。

修改 `app/` 中的文件后，可复制对应修改到工作目录，或保留旧工作目录并用 `--output "work/another-build"` 创建新的副本。不要复制 `.aura-photo-data`。

```powershell
& ".\work\AURA Photo\runtime\python.exe" ".\work\AURA Photo\portable_bootstrap.py"
```

已观察到的依赖版本列于 `requirements-*-observed.txt`，详细元数据见 `app/licenses/runtime-inventory.json`。这些是版本快照，**不是保证一条 pip 命令就能重建 Windows 二进制环境的安装锁文件**；CPU Torch、CUDA Torch、渲染依赖分开存放，不能混装到一个 site-packages。

## 2. 词条与启动器

```powershell
python compile_catalog.py
# 将更新后的 app/locales 复制到工作副本，然后编译启动器：
powershell -NoProfile -File tools/build_launcher.ps1 -AppDir "work/AURA Photo"
```

词条编号对应 `localization/messages.json` 的固定顺序；不要重新排序。完整 C# 源码为 `app/source/Launcher.cs`，需 Windows .NET Framework 4.x C# 编译器。

## 3. 安装器

安装 Inno Setup 6.5 或兼容版本，运行：

```powershell
python tools/build_installer.py --app-dir "work/AURA Photo" --compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

输出 `dist/0.2.0`，包含 EXE 和三个 BIN。脚本重新生成分发哈希，排除个人数据和日志。固定 AppId 为 `C8F2915C-BBA6-4AB2-BFE5-6377282D28F4`，采用 `installer_policy.write_installer_script` 输出脚本，升级锁定已有目录、保留偏好、运行中不强制结束应用。后续版本应保持该 AppId 不变，以便识别已有安装。

发布改版时同步更新 Python、C# 和安装脚本中的版本。当前脚本服务于本次 0.2.0 快照，不自动发行新版本。

## 4. 自检

```powershell
& ".\work\AURA Photo\runtime\python.exe" ".\work\AURA Photo\portable_bootstrap.py" --self-test --report "work/smoke.json"
```

加 `--input PHOTO --relight --raw-input RAW` 执行真实照片、模型和 RAW 检查；先正常启动一次并按提示初始化 GPU 渲染。强制 CPU 可设置 `BEAUTY_PORTABLE_CPU=1`、`BEAUTY_AI_DEVICE=cpu`、`AURA_RENDER_BACKEND=cpu`。测试输出写到 `work/`，不提交测试照片和报告中的本机路径。

## 第三方重建与分发

安装目录 `third-party-sources` 中有 45 份对应源码归档；哈希、上游 URL、版本、PKGBUILD 与构建说明在 `licenses`、`SOURCE_BUILD_INSTRUCTIONS.txt`。RawTherapee 及 DLL 曾与官方二进制逐文件比对；不声称已重新编译全部第三方库或达到逐字节可复现。

从零重建时依据这些上游构建脚本和版本准备依赖，并重新验证 ABI、模型哈希、CPU/GPU 和导出流程。源码仓库没有附带 CUDA 专有运行库；使用和再分发它们仍受 NVIDIA 许可约束。不能把项目的许可证套到整个安装目录。
