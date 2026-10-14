AURA Photo 0.2.0 — Windows standalone still photo edition (GPU + CPU)

INSTALL AND LANGUAGE
Keep the Setup EXE and every accompanying BIN file together. Run Setup and choose English or Simplified Chinese. The application starts in that language on first use.
Open Settings > Language to switch immediately. Your photo and edit state remain in place, and the choice is remembered next time. Updates preserve a language preference changed inside the application.
This edition has its own installation folder, shortcut and uninstall entry. It does not replace the original AURA. Updates reuse this edition's installation folder. Save your work and close AURA Photo before updating.

RUN AND DATA
Launch AURA Photo.exe. No separate Python, CUDA Toolkit or original AURA installation is required. Settings, recovery records and GPU caches are stored in .aura-photo-data inside this edition's folder. Export creates separate files; source photos are retained.
The complete application folder can also be moved after closing the application. Local directory junctions provide CUDA compatibility with non-ASCII paths; they do not create copies of your photos.

GPU
NVIDIA CUDA 13, cuDNN, PyTorch, ONNX Runtime and CuPy runtime libraries are included. First use of GPU rendering asks for permission to download a small official NVIDIA header package; later use can work offline. A compatible NVIDIA driver is required. Verified on RTX 5060 Ti 16 GB with driver 610.88; other GPUs have not all been tested.
CPU fallback is available automatically or through Launch CPU.cmd. MediaPipe detection and some ONNX operators use the CPU normally.

FEATURES
Still photos, RAW development, portrait beauty, local repair, reshaping, color adjustments, geometry relighting, and JPEG / PNG / TIFF export.
RawTherapee 5.13 retains as-shot white balance, lens matching and manual controls. Default user exposure is 0; no fixed +0.35 EV is added. Camera DCP collections are not bundled. Base camera matrices can produce different colors from the original edition's DCP-based output. Import only profiles you are entitled to use.
No Fujifilm filter collection, HEIC, Live Photo or video processing in this edition. MediaPipe models replace the previous facial segmentation and alignment dependencies. Review masks around fine hair, occlusions and profiles; manual refinement is available.

DISTRIBUTION
Retain THIRD_PARTY_NOTICES.txt, licenses, models-manifest.json, third-party-sources and SOURCE_BUILD_INSTRUCTIONS.txt with the complete package. Personal photos, test exports and local recovery records are excluded from the installer.
Third-party licenses do not establish a single open-source license for the entire AURA project. The project owner determines the project's own distribution license.


AURA license / AURA 项目许可
GitHub: zhfscg123-beep — https://github.com/zhfscg123-beep
See LICENSE-AURA.txt. Personal noncommercial use and free sharing are permitted; commercial use and defined bulk distribution require prior written permission. Third-party and GitHub platform rights are preserved.
详见 LICENSE-AURA.txt：允许个人非商业使用和免费分享，不限个人分享下载次数；商业使用与所定义的批量分发须另行书面授权。第三方许可与 GitHub 平台权利保留。
