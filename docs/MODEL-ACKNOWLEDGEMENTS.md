# 模型来源与致谢 / Model provenance and acknowledgements

核对日期 / Checked: 2026-10-13。范围 / Scope: AURA Photo 0.2.0.

感谢这些项目的作者、维护者及贡献者公开其研究、代码、模型与转换工作。下表覆盖 `app/models-manifest.json` 中全部 10 个 active_models 文件条目；天空模型的图结构和权重为一对文件。它不是对软件全部第三方运行库的完整列举。

Thank you to the authors, maintainers and contributors for their research, code, models and conversion work. The table covers all 10 active file entries in the bundled model manifest; the sky model uses a graph/weight file pair. This is a model inventory, not the complete runtime-dependency list.

| 本版文件 / Bundled file | 对应 GitHub 项目 / GitHub project |
| --- | --- |
| `face_landmarker.task` | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) |
| `pose_landmarker_full.task` | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) |
| `selfie_multiclass_256x256.tflite` | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) |
| `damo_local.pth` | [modelscope/modelscope](https://github.com/modelscope/modelscope) |
| `damo_blend.pth` | [modelscope/modelscope](https://github.com/modelscope/modelscope) |
| `face_detection_yunet_2023mar.onnx` | [opencv/opencv_zoo/tree/main/models/face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| `lama_fp32.onnx` | [advimman/lama](https://github.com/advimman/lama) · [Carve-Photos/lama](https://github.com/Carve-Photos/lama) |
| `relight/moge-small/model.pt` | [microsoft/MoGe](https://github.com/microsoft/MoGe) |
| `scene/skysegsmall_sim-opt-fp16.param` | [xiongzhu666/Sky-Segmentation-and-Post-processing](https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing) |
| `scene/skysegsmall_sim-opt-fp16.bin` | [xiongzhu666/Sky-Segmentation-and-Post-processing](https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing) |

## 权重发布与实现 / Weight publication and implementation

- **MediaPipe:** GitHub 项目为 google-ai-edge/mediapipe；本版模型来自 Google 的官方模型分发地址，具体 URL、模型卡及哈希见 [manifest](../app/models-manifest.json)。Model bundles are distributed through Google's official model endpoints, as recorded in the manifest.
- **DAMO:** [ModelScope 模型页 / model page](https://www.modelscope.cn/models/damo/cv_unet_skin-retouching)。AURA 的 `damo_local.pth` 对应 `joint_20210926.pth`，`damo_blend.pth` 对应 `pytorch_model.pt`。适配代码来自 ModelScope 1.40.1 的 `modelscope/models/cv/skin_retouching`，本地记录见 [sources.json](../app/vendor/damo/sources.json)。These are local names for the upstream weights; ModelScope supplies the implementation and model hosting.
- **YuNet:** 使用 OpenCV Zoo 的 `face_detection_yunet_2023mar.onnx`。上游训练项目为 [ShiqiYu/libfacedetection.train](https://github.com/ShiqiYu/libfacedetection.train)。The training project is credited as upstream provenance; this does not claim AURA bundles that training pipeline.
- **LaMa:** 原始研究与实现为 [advimman/lama](https://github.com/advimman/lama)。本版 `lama_fp32.onnx` 来自 [Carve/LaMa-ONNX](https://huggingface.co/Carve/LaMa-ONNX)，其模型卡链接到 [Carve-Photos/lama](https://github.com/Carve-Photos/lama) 转换实现。Both the original authors and the ONNX conversion contributors are credited.
- **MoGe:** 使用 [Ruicheng/moge-2-vits-normal](https://huggingface.co/Ruicheng/moge-2-vits-normal) 的 MoGe-2 Small。AURA 用其深度与法线输出实现自身几何补光；补光算法不归称为 MoGe 原生功能。AURA uses estimated depth and normals as inputs to its own relighting implementation.
- **Sky:** 本版图结构与权重来自 [Sky-Segmentation-and-Post-processing](https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing)，具体提交见 manifest。该上游说明其小模型使用 U2NETP 训练。The upstream project identifies U2NETP as the small sky model architecture.

## 基础模型致谢 / Underlying model acknowledgements

- [facebookresearch/dinov2](https://github.com/facebookresearch/dinov2)：MoGe 内的 DINOv2 编码器；本地实现见 [dinov2_encoder.py](../app/vendor/moge/model/modules/dinov2_encoder.py)，并保留 [DINOv2 LICENSE](../app/vendor/moge/model/modules/dinov2/LICENSE)。This is part of MoGe's architecture, not an additional separate model download in the active manifest.
- [xuebinqin/U-2-Net](https://github.com/xuebinqin/U-2-Net)：Sky 模型的 U²-Net / U2NETP 架构来源。This credits the architecture; it does not claim that AURA uses the original project's generic salient-object weights.

## 版本与权利 / Versions and rights

这里只列出 AURA Photo 0.2.0 实际使用的模型及相关上游基础。上游仓库可能继续更新；模型文件与 SHA-256 以 [manifest](../app/models-manifest.json) 为准。源码项目、模型权重及转换实现分别适用其许可证，不根据仓库首页给全部模型作统一授权判断。

This inventory covers the models used by AURA Photo 0.2.0 and their upstream foundations. Upstream repositories may evolve; the manifest pins the files and hashes used by this release. Source, weights and converted artifacts retain their respective license conditions. These acknowledgements do not imply endorsement, affiliation or new licensing rights.

完整分发声明 / Full distribution notices: [THIRD_PARTY_NOTICES.txt](../app/THIRD_PARTY_NOTICES.txt).
