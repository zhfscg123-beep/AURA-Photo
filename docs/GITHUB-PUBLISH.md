# GitHub 上传安排

项目仓库：[zhfscg123-beep/AURA-Photo](https://github.com/zhfscg123-beep/AURA-Photo)。本文件说明维护者的发布流程。项目已采用 `LICENSE` 中的自定义非商业使用与个人免费分享许可；公开署名为 `zhfscg123-beep`。这是源码可见项目，不能标注为 MIT / Apache / GPL 或 OSI 开源项目。

## 仓库

提交 `source` 目录内部的文件，而不是把整个项目磁盘目录拖入 GitHub。`.gitignore` 已排除运行库、模型权重、工作目录、个人项目、RAW、偏好和缓存。第三方许可、模型来源、适配源码与构建工具保留。

源码 ZIP 是一个便利下载附件；真正的 Git 仓库应存解压后的源文件，便于追踪修改。不要提交安装 EXE / BIN、大型权重或 `.aura-photo-data`。

## Releases

同一 Release 上传以下四个安装文件，文件名保持不变：

- `AURA-Photo-0.2.0-Windows-GPU-Setup.exe`
- `AURA-Photo-0.2.0-Windows-GPU-Setup-1.bin`
- `AURA-Photo-0.2.0-Windows-GPU-Setup-2.bin`
- `AURA-Photo-0.2.0-Windows-GPU-Setup-3.bin`

同时上传源码 ZIP、`LICENSE-AURA.txt`、`SHA256SUMS.txt` 和安装说明。下载者需要四个安装文件全部在同一目录。BIN 是 Inno Setup 的安装分卷，不是可分别解压的 ZIP。

完整安装包不应合并为单个 GitHub Release 附件。GitHub 的 Release 文档要求每个附件小于 2 GiB；普通 Git 文件超过 100 MiB 会被拒绝。当前每个安装分卷均小于 2 GiB。[Release 限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) · [普通文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

安装包内已保留对应第三方源码及许可目录，不能为减小体积删除这些分发材料。若之后另外拆分第三方源码下载，需重新核对适用许可证要求及获取方式，不直接沿用本次验证结论。

## 0.2.0 发布说明

AURA Photo 0.2.0 面向 Windows x64，支持静态照片编辑，包含 NVIDIA GPU 与 CPU 环境。支持中英文安装及设置内即时语言切换、RAW、美颜、局部修复、调色、几何补光、JPEG/PNG/TIFF 导出。

不包含富士滤镜集合、HEIC、实况照片、视频和相机 DCP 集合。首次启用 GPU 渲染按提示完成初始化。安装前保存并退出应用，后续更新保留本版设置。

源码与发布材料已进行隐私检查，安装包经过 GPU、CPU、RAW 显影与导出验证。具体校验和以同一 Release 的 `SHA256SUMS.txt` 为准。

本次许可更新已同步到源码和安装器许可页面；使用最新 EXE、全部三个 BIN 和校验值，勿混用此前分卷。个人免费转载允许，商业使用及定义的批量分发须另行书面授权；第三方许可和 GitHub 平台内 Fork 权利保留。
