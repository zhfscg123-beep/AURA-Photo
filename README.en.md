# AURA Photo

**Local portrait retouching, repair, color adjustment and relighting for still photos.**

[简体中文](README.md) · English

AURA Photo is a Windows desktop portrait editor with still-image and RAW workflows, GPU and CPU runtimes, and a switchable Chinese/English interface.

This guide covers **AURA Photo 0.2.0**, which currently supports still-photo editing.

> **License summary:** Personal noncommercial use, study, modification and free sharing are permitted without a download-count cap. Commercial use and the bulk distribution or centralized deployment defined in the license require prior written permission. This is a **source-available project**, not an OSI-defined open-source project. See [LICENSE](LICENSE) for full terms. Third-party components retain their own licenses.

## Features

| Area | Current support |
| --- | --- |
| Portrait retouching | Skin tone and whitening adjustments, texture processing, local reshaping |
| Local repair | Repair selected areas and refine mask boundaries manually |
| Color and lighting | Color controls and geometry-based relighting |
| RAW development | RawTherapee / LibRaw processing, as-shot white balance, lens-profile matching and manual adjustments |
| Export | JPEG, PNG and TIFF; 16-bit TIFF export has been verified |
| Acceleration | NVIDIA GPU model inference and rendering, with a CPU runtime available |
| Languages | Simplified Chinese and English; select during installation or change in Settings |

Basic whitening includes the eyebrow region, while texture processing continues to protect eyebrow detail. Masks around fine hair, occlusions and profiles may need manual refinement.

## Download and install

Use the repository's [**Releases**](https://github.com/zhfscg123-beep/AURA-Photo/releases/tag/v0.2.0) page to obtain published installation files. The complete 0.2.0 installer consists of these four files, totaling approximately **3.6 GB**:

```text
AURA-Photo-0.2.0-Windows-GPU-Setup.exe
AURA-Photo-0.2.0-Windows-GPU-Setup-1.bin
AURA-Photo-0.2.0-Windows-GPU-Setup-2.bin
AURA-Photo-0.2.0-Windows-GPU-Setup-3.bin
```

1. Download all four files from the same release and keep them in one directory.
2. Run `Setup.exe`, read the license and choose English or Simplified Chinese.
3. Launch **AURA Photo**, import a photo, adjust the result and export it.

The BIN files are installer data volumes; do not extract them separately. Do not mix files from different builds. Compare downloaded files against the release attachment `SHA256SUMS.txt` if needed.

**The installer includes the required runtimes; normal use needs no separate Python or CUDA Toolkit installation.** GitHub source downloads and `AURA-Photo-0.2.0-Source.zip` are for development; they are not the installer with models and runtimes.

### Runtime requirements

- **OS:** Windows x64. No macOS or Linux installer is currently provided.
- **GPU:** An NVIDIA GPU and driver compatible with the included CUDA 13 runtime. The GPU driver is not included.
- **CPU:** A CPU environment is available when a usable GPU is absent. Use `Launch CPU.cmd` in the installation directory to request CPU mode.
- **Storage:** Allow additional space for installation, extraction and processing caches beyond the downloaded files.

The 0.2.0 GPU workflow was tested on an RTX 5060 Ti 16 GB with driver 610.88. This is a tested configuration, not a minimum specification or a guarantee for every GPU.

### First-use GPU rendering

On first use, GPU rendering asks permission to download a small set of required compilation headers from an official NVIDIA source and checks a pinned SHA-256. Later rendering can reuse the local cache.

Declining the download, or a failed download, still allows GPU model inference with CPU photo rendering; a CPU environment is also available. MediaPipe localization and some ONNX operators normally run on the CPU.

## Usage and local data

- **Language:** Open **Settings → Language / 设置 → 语言**. The choice is remembered, and upgrades preserve a preference changed inside the application.
- **Editing and export:** Core image processing runs locally. Results can be exported to separate files.
- **Application data:** Preferences, recovery records and GPU caches live in `.aura-photo-data` inside the application directory. Exclude this directory when redistributing.
- **Updates:** Save your work and exit AURA Photo before running an update. Updates reuse the existing installation directory and retain your settings.

## Scope and limitations

AURA Photo focuses on still photos. It currently **does not provide the Fujifilm filter collection, HEIC, Live Photo or video processing**, and does not bundle camera DCP collections.

The default user RAW exposure is **0** and can be adjusted manually. Camera color profiles and processing pipelines affect the result, so color and brightness may differ from other RAW software or camera JPEG output.

Occlusions, profiles and fine boundaries may require mask corrections. Performance also depends on the hardware, driver and image dimensions.

## Development and building

The repository contains application and launcher source, translations, UI resources, third-party adaptation source and license materials. Model weights, Python/CUDA runtimes and RAW-tool binaries are supplied in the installer and excluded from the ordinary Git source tree.

Use Windows x64, Python 3.12 and a complete installation of the matching AURA Photo version. From the repository root:

```powershell
python tools/create_development.py --base-dir "C:\Apps\AURA Photo"
& ".\work\AURA Photo\runtime\python.exe" ".\work\AURA Photo\portable_bootstrap.py"
```

Replace the example installation path with your own. The tool verifies distributed files, creates an isolated copy in `work/AURA Photo`, and overlays repository source. It excludes personal preferences, photos and recovery data. The output work directory must be new.

See [Build instructions](docs/BUILD.md) for translation compilation, launcher and installer builds, and self-tests. That detailed guide is currently in Chinese. The `requirements-*-observed.txt` files are version snapshots, not a single installation lockfile for mixing CPU and GPU dependencies.

```text
app/                  Application, UI resources, third-party notices and model provenance
localization/         Chinese/English messages and translation materials
tools/                Development-copy, launcher, installer and source-check tools
docs/                 Build, licensing, publication and verification notes
LICENSE               License for applicable AURA-owned portions
README.md             Chinese documentation
```

## Verification

Local release preparation for 0.2.0 included:

- Per-file installed payload size and SHA-256 verification.
- GPU and CPU launch, model execution, RAW development and 16-bit TIFF export.
- Paths containing Chinese characters or spaces, initial language selection and preference retention.
- In-place upgrades retaining the installation directory, settings, photos and projects.
- A source development-copy self-test and compilation of the installer build tool.

See the [verification record](docs/VERIFICATION.json) for scope. These checks cover the tested environment, not every hardware configuration, camera format or third-party dependency. They do not establish byte-for-byte reproducible builds of third-party dependencies.

See the [source privacy review](docs/SOURCE-PRIVACY-REVIEW.txt) for the release review scope and remediation.

## Licensing and third-party components

The project uses the **AURA Noncommercial Use and Personal Free Sharing License 1.0**, with public attribution to [zhfscg123-beep](https://github.com/zhfscg123-beep).

| Activity | License summary |
| --- | --- |
| Personal noncommercial use, research and modification | Permitted |
| Personal free sharing of unmodified or modified versions | Permitted; preserve notices and identify modifications |
| A personal share receives many downloads | No download, view or recipient-count cap |
| Forking within GitHub | Rights allowed by the platform terms are preserved |
| Commercial use, including paid photo editing and business operations | Prior written permission required |
| Bulk software-site listing, automated mirroring, centralized organizational deployment or bundling | Prior written permission required as defined in LICENSE |

This table is a summary; [LICENSE](LICENSE) controls the definitions, exceptions and conditions. Identify the authorizing party through the named GitHub account and channels expressly announced by it. No contact email is currently provided. Stars, forks and downloads do not grant additional commercial permission.

Third-party models, code, runtimes and data remain under their own licenses. **The project's additional commercial-use and distribution restrictions do not apply to those third-party components.** Their own redistribution conditions still apply. The installer retains the relevant license and corresponding-source materials.

- [Third-party notices](app/THIRD_PARTY_NOTICES.txt)
- [Model provenance and checksums](app/models-manifest.json)
- [Third-party source and build notes](app/SOURCE_BUILD_INSTRUCTIONS.txt)
- [Project licensing notes](docs/LICENSE-OPTIONS.md)

## Third-party model acknowledgements

AURA Photo's model features build on the research, code, models and conversion work published by the projects below. We thank their authors, maintainers and contributors. This table covers the models **actually used by AURA Photo 0.2.0** and their roles in AURA Photo.

| Model / project | Role in AURA Photo | GitHub project |
| --- | --- | --- |
| MediaPipe Face Landmarker, Pose Landmarker Full and Selfie Multiclass | Face geometry and feature localization, pose/silhouette estimation, and skin/hair/clothing segmentation | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) |
| DAMO Skin Retouching / ModelScope | Local blemish detection and repair, plus learned blend maps for regional facial texture controls | [modelscope/modelscope](https://github.com/modelscope/modelscope) |
| YuNet (2023mar) | Small-face candidate localization supporting subsequent landmark detection | [opencv/opencv_zoo — YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| LaMa / Carve ONNX conversion | Inpainting and content completion in selected regions | [advimman/lama](https://github.com/advimman/lama) · [Carve-Photos/lama](https://github.com/Carve-Photos/lama) |
| MoGe-2 Small (vits-normal) | Depth and surface-normal estimation used by AURA's geometric relighting | [microsoft/MoGe](https://github.com/microsoft/MoGe) |
| Sky U2Net-small | Sky segmentation | [xiongzhu666/Sky-Segmentation-and-Post-processing](https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing) |

We also acknowledge these underlying model and training projects:

- [facebookresearch/dinov2](https://github.com/facebookresearch/dinov2): the DINOv2 encoder foundation used within MoGe.
- [xuebinqin/U-2-Net](https://github.com/xuebinqin/U-2-Net): the U²-Net / U2NETP architecture used by the sky segmentation model.
- [ShiqiYu/libfacedetection.train](https://github.com/ShiqiYu/libfacedetection.train): the upstream YuNet training project referenced by OpenCV Zoo's model documentation.

DAMO weights come from the [ModelScope model page](https://www.modelscope.cn/models/damo/cv_unet_skin-retouching), the actual LaMa ONNX file from [Carve/LaMa-ONNX](https://huggingface.co/Carve/LaMa-ONNX), and MoGe-2 Small weights from [Ruicheng/moge-2-vits-normal](https://huggingface.co/Ruicheng/moge-2-vits-normal). Source repositories and weight publication locations are distinguished in the [model acknowledgement inventory](docs/MODEL-ACKNOWLEDGEMENTS.md).

The [model manifest](app/models-manifest.json) identifies the exact bundled files, versions and SHA-256 values. Acknowledgement does not imply endorsement or affiliation, and does not replace upstream licenses or copyright notices. AURA's commercial-use and distribution restrictions do not alter rights granted by third-party licenses.

## Feedback

If Issues are enabled for the repository, use them for bug reports or feature suggestions. Include the application version, Windows and GPU/driver details, input image format, steps to reproduce and error messages. Providing a reproduction image is optional.

Discussion and suggestions for personal use are welcome. Changes and redistribution remain subject to the applicable licenses; obtain permission before commercial use or the restricted distribution and deployment activities.
