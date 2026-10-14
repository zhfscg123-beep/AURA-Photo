# AURA Photo

**允许你在本地完成静态人像照片的美颜、修复、调色与补光。**

简体中文 · [English](README.en.md)

AURA Photo 是面向 Windows 的桌面人像照片编辑软件，支持普通静态照片与 RAW 显影，提供 GPU 和 CPU 运行环境，以及可随时切换的中英文界面。

本文对应 **AURA Photo 0.2.0**，当前支持静态照片编辑。

> **许可摘要：**允许个人非商业使用、学习修改和免费转载，不限制个人分享的下载次数。商业使用及许可中定义的批量分发、集中部署须另行取得书面授权。本项目采用自定义的**源码可见许可**，不是 OSI 定义的开源项目。完整条件见 [LICENSE](LICENSE)，第三方组件保留各自许可证。

## 功能

| 功能 | 当前支持 |
| --- | --- |
| 人像美颜 | 肤色与美白调整、纹理处理、局部形变 |
| 局部修复 | 对选定区域进行修复，并支持手动修正蒙版边界 |
| 调色与补光 | 色彩调整、几何补光 |
| RAW 显影 | RawTherapee / LibRaw 处理链路，拍摄白平衡、镜头配置匹配与手动调整 |
| 导出 | JPEG、PNG、TIFF；已验证 16 位 TIFF 导出 |
| 加速 | NVIDIA GPU 模型推理与渲染，同时提供 CPU 环境 |
| 语言 | 简体中文 / English；安装时选择，应用设置内可更改 |

基础美白包含眉部区域，纹理处理仍保护眉毛。面对细发丝、遮挡和侧脸等情况，可以检查蒙版并手动修正边界。

## 下载与安装

在本仓库的 [**Releases**](https://github.com/zhfscg123-beep/AURA-Photo/releases/tag/v0.2.0) 页面获取已发布的安装文件。0.2.0 的完整安装包由以下四个文件组成，合计约 **3.6 GB**：

```text
AURA-Photo-0.2.0-Windows-GPU-Setup.exe
AURA-Photo-0.2.0-Windows-GPU-Setup-1.bin
AURA-Photo-0.2.0-Windows-GPU-Setup-2.bin
AURA-Photo-0.2.0-Windows-GPU-Setup-3.bin
```

1. 下载同一发布版本的全部四个文件，放在同一目录。
2. 运行 `Setup.exe`，阅读许可，并选择简体中文或 English。
3. 安装完成后启动 **AURA Photo**，导入照片、调整效果并导出。

BIN 文件是安装器的数据分卷，不需要单独解压。请使用同一套 EXE 和 BIN，避免混用不同批次的文件；可用发布附件 `SHA256SUMS.txt` 核对下载结果。

**安装包已包含所需运行环境，普通使用无需另装 Python 或 CUDA Toolkit。** GitHub 的源码下载和 `AURA-Photo-0.2.0-Source.zip` 用于开发，不是包含模型和运行环境的安装包。

### 运行环境

- **系统：**Windows x64。
- **GPU：**需要与所附 CUDA 13 运行库兼容的 NVIDIA 显卡和驱动；安装包不包含显卡驱动。
- **CPU：**没有可用 GPU 时可使用 CPU 环境，也可通过安装目录中的 `Launch CPU.cmd` 启动。
- **存储：**除下载文件外，还需为程序安装、解压和处理缓存预留空间。


### 首次 GPU 渲染

首次启用 GPU 渲染时，应用会询问是否从 NVIDIA 官方来源下载所需的少量编译头文件，并核对固定 SHA-256。初始化完成后，后续渲染可使用本地缓存。

如果拒绝下载或下载失败，仍可使用 GPU 模型推理与 CPU 照片渲染；也可以切换至 CPU 环境。MediaPipe 定位和部分 ONNX 算子本身在 CPU 上运行，属于正常分工。

## 使用与数据

- **语言切换：**打开 **设置 → 语言 / Settings → Language**。选择会被记住；更新保留已在应用内修改的语言偏好。
- **编辑与导出：**核心图像处理在本机完成，处理结果可另存为新文件。
- **本地数据：**设置、恢复记录及 GPU 缓存位于程序目录的 `.aura-photo-data` 中。重新分发时不要包含该目录。
- **版本更新：**先保存并退出 AURA Photo，再运行更新安装器；更新沿用已有安装目录和设置。

## 当前范围与限制

AURA Photo 专注于静态照片，**暂不提供富士滤镜集合、HEIC、实况照片或视频处理**，也不捆绑相机 DCP 集合。

RAW 的用户曝光默认值为 **0**，支持手动调整。不同的相机色彩配置和显影流程会影响结果，因此色彩与亮度可能与其他 RAW 软件或相机 JPEG 不同。

模型识别结果可能在遮挡、侧脸或细小边界处需要人工调整。不同硬件、驱动和照片尺寸下的运行表现也会有所不同。

## 开发与构建

仓库包含应用源码、启动器源码、词条、界面资源、第三方适配源码和许可材料。模型权重、Python/CUDA 运行库及 RAW 工具二进制位于安装包中，不放入普通 Git 源码树。

开发时使用 Windows x64、Python 3.12 和同版本的完整 AURA Photo 安装目录。在仓库根目录执行：

```powershell
python tools/create_development.py --base-dir "C:\Apps\AURA Photo"
& ".\work\AURA Photo\runtime\python.exe" ".\work\AURA Photo\portable_bootstrap.py"
```

将示例路径替换为实际安装位置。工具会校验分发文件，在 `work/AURA Photo` 建立隔离副本并覆盖仓库中的源码，不复制个人偏好、照片或恢复数据。目标工作目录必须是新目录。

完整的词条编译、启动器构建、安装器打包和自检步骤见 [构建说明](docs/BUILD.md)。`requirements-*-observed.txt` 是依赖版本快照，不是可直接混装全部 CPU/GPU 依赖的一键安装锁文件。

```text
app/                  应用、界面资源、第三方声明及模型来源
localization/         中英文词条与翻译材料
tools/                开发副本、启动器、安装器及源码核验工具
docs/                 构建、许可、发布与验证说明
LICENSE               项目自有部分适用的许可
README.en.md          English documentation
```

## 验证记录

0.2.0 发布准备已完成以下本地验证：

- 安装载荷逐文件大小与 SHA-256 校验。
- GPU 与 CPU 启动、模型运行、RAW 显影及 16 位 TIFF 导出。
- 中文及空格路径、中英文默认语言和语言偏好保留。
- 覆盖升级复用目录，保留设置、照片和项目。
- 源码工作副本自检及安装器构建工具编译。

具体范围见 [验证记录](docs/VERIFICATION.json)。这些记录对应测试过的环境，不代表所有硬件、相机格式或第三方库都已经逐一验证，也不声称第三方依赖实现了逐字节可复现构建。

源码发布前的检查范围和处理结果见 [源码隐私检查](docs/SOURCE-PRIVACY-REVIEW.txt)。

## 许可与第三方组件

项目采用 **AURA 非商业使用与个人免费分享许可 1.0**，公开署名为 [zhfscg123-beep](https://github.com/zhfscg123-beep)。

| 使用方式 | 许可摘要 |
| --- | --- |
| 个人非商业使用、研究、修改 | 允许 |
| 个人免费转载未修改版本或修改版本 | 允许；保留声明，修改版需清楚标明 |
| 个人分享被大量下载 | 不按下载次数、浏览量或接收人数设限 |
| GitHub 平台内 Fork | 保留平台条款允许的权利 |
| 商业使用，包括收费修图与企业经营流程 | 须事先取得书面授权 |
| 软件站批量收录、自动镜像、组织集中部署、捆绑分发 | 按 LICENSE 定义，须事先取得书面授权 |

以上为摘要，具体定义、例外和条件以 [LICENSE](LICENSE) 为准。授权身份以该 GitHub 账号及其明确公布的授权渠道为依据；目前不提供联系邮箱。Star、Fork 或下载不构成额外商业授权。

第三方模型、代码、运行库和数据始终遵守各自许可证，**不受本项目新增商业及分发限制的约束**。分发相关组件时仍需履行其自身许可要求。安装包保留相应许可证及对应源码材料。

- [第三方声明](app/THIRD_PARTY_NOTICES.txt)
- [模型来源与校验值](app/models-manifest.json)
- [第三方构建与源码说明](app/SOURCE_BUILD_INSTRUCTIONS.txt)
- [项目许可说明](docs/LICENSE-OPTIONS.md)

## 第三方模型致谢

AURA Photo 的模型功能建立在以下项目公开的研究、代码、模型及转换工作之上。感谢各项目作者、维护者和贡献者。下面列出 **AURA Photo 0.2.0 实际使用的模型**及其在本软件中的用途。

| 模型 / 项目 | 在 AURA Photo 中的用途 | GitHub 项目 |
| --- | --- | --- |
| MediaPipe Face Landmarker、Pose Landmarker Full、Selfie Multiclass | 人脸网格与五官定位、人体姿态及轮廓、皮肤/头发/衣物等分区 | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) |
| DAMO Skin Retouching / ModelScope | 局部瑕疵检测与修复，以及区域性面部纹理调整所用的融合图 | [modelscope/modelscope](https://github.com/modelscope/modelscope) |
| YuNet（2023mar） | 小人脸候选定位，辅助后续人脸关键点检测 | [opencv/opencv_zoo — YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| LaMa / Carve ONNX 转换 | 对选定区域进行图像修复和内容补全 | [advimman/lama](https://github.com/advimman/lama) · [Carve-Photos/lama](https://github.com/Carve-Photos/lama) |
| MoGe-2 Small（vits-normal） | 估计深度与表面法线，为 AURA 的几何补光提供输入 | [microsoft/MoGe](https://github.com/microsoft/MoGe) |
| Sky U2Net-small | 天空区域分割 | [xiongzhu666/Sky-Segmentation-and-Post-processing](https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing) |

同时感谢以下基础模型与训练项目：

- [facebookresearch/dinov2](https://github.com/facebookresearch/dinov2)：MoGe 中使用的 DINOv2 编码器基础。
- [xuebinqin/U-2-Net](https://github.com/xuebinqin/U-2-Net)：天空分割模型使用的 U²-Net / U2NETP 架构基础。
- [ShiqiYu/libfacedetection.train](https://github.com/ShiqiYu/libfacedetection.train)：YuNet 上游训练项目，由 OpenCV Zoo 的模型说明引用。

DAMO 权重来自 [ModelScope 模型页](https://www.modelscope.cn/models/damo/cv_unet_skin-retouching)，LaMa 的实际 ONNX 文件来自 [Carve/LaMa-ONNX](https://huggingface.co/Carve/LaMa-ONNX)，MoGe-2 Small 权重来自 [Ruicheng/moge-2-vits-normal](https://huggingface.co/Ruicheng/moge-2-vits-normal)。GitHub 源码项目和权重发布位置分别注明；模型文件、上游关系及来源详见 [模型致谢清单](docs/MODEL-ACKNOWLEDGEMENTS.md)。

AURA Photo 0.2.0 采用的具体文件、版本和 SHA-256 以 [模型清单](app/models-manifest.json) 为准。致谢不代表上游对 AURA 的认可或合作关系，也不替代其许可证及版权声明；本项目的商业与分发限制不改变第三方组件自身授予的权利。

## 问题反馈

如仓库已开启 Issues，可提交功能建议或问题。为便于复现，请附上应用版本、Windows 与显卡/驱动信息、输入图片格式、操作步骤和错误提示；复现图片可自愿提供。

欢迎交流个人使用与改进建议。当前仓库许可同样适用于相应修改与再分发；涉及商业用途或批量部署时，请先按许可取得授权。
