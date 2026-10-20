# 本地声纹模型

`pet_owner_sv_s3.espdl` 是桌宠的实验模型，不代表已完成真人身份验证验收。

- 来源：[Espressif ESP-DL speaker_verification](https://github.com/espressif/esp-dl/tree/98fbf318f35f9e24151ae70e2fb6560eb0578a92/models/speaker_verification)，提交 `98fbf318f35f9e24151ae70e2fb6560eb0578a92`。
- 原始模型：`models/p4/sv_tdnn_tiny_3s.espdl`，2,844,528 字节，SHA256 `736ca24bc3430db65b063ce4af7341904d1970d8505aa2eaab0d7be9e760c42e`。
- 许可证：MIT，原许可见 `LICENSE.esp-dl`。未下载或宣称拥有原始训练数据/浮点权重。
- 方法：解开 SIMD 参数布局，反量化已发布权重，重建浮点 ONNX 参考，再用 ESP-PPQ 1.3.11 针对 ESP32-S3 做逐张量 16 位量化。重建参考与原始训练浮点模型不同；官方 P4 模型的 EER 不能沿用为本模型结果。
- 结构：TDNN 帧层、均值/标准差池化、512 维输出；16kHz 单声道 PCM，80 维 Fbank、逐句均值归一化，300 帧（3.015 秒窗口）。长录音中心裁剪；录入阶段要求至少三秒。
- 优化：卷积时间轴映射到高度，启用 ESP-DL 双核调度；单维度升降维不改变浮点计算。Sqrt 池化处可使用浮点运算，不能把此模型称作每个算子都为整数。
- 当前产物：3,783,312 字节，SHA256 `21b1c3e5b13a6a1654f7c75b458e6597742ccd117a97418321bd8fddf4608541`。主程序 `pet_owner_model.h` 和每份主人记录绑定该 SHA256。
- 模型内测试向量来自乐鑫例程公开音频，不含用户录音。用户语音不会写进模型，也不会为本地核验上传。

转换工具及完整说明位于 `../experiments/local_owner/`。库升级或模型重生成后，需要重新验证输出、峰值内存、延迟与真人误认/误拒；更改模型 SHA 会阻止直接复用旧主人模板，不能忽略这个检查。
