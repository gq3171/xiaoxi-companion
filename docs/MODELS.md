# 多模型接入

小溪不绑定某一家大模型。对话、出生设定解析、自主规划、反思和电脑任务共用可选择的文本后端；ASR（识别）、TTS（合成）、搜索是独立服务。换模型保留同一份身份、记忆与任务状态。模型仍需能按提示输出小溪使用的结构化 JSON；小模型的能力不能由协议兼容保证。

## 接入协议与预设

| `LLM_PROVIDER` | 默认协议 | 地址来源 / 说明 |
|---|---|---|
| `minimax` | `minimax-messages` | 保留现有 MiniMax Messages、effort 和流式行为 |
| `openai` | `openai-responses` | `/v1/responses`，默认不附加模型特有的 temperature/effort |
| `anthropic` | `anthropic` | `/v1/messages`，使用 Anthropic 鉴权 |
| `deepseek` | `openai-chat` | 官方 Chat 兼容接口 |
| `qwen` | `openai-chat` | 百炼兼容接口，需核对地域/工作空间地址 |
| `doubao` | `openai-chat` | 方舟 Chat 接口，模型可能要填写你的接入点 ID |
| `gemini` | `openai-chat` | Gemini 官方 OpenAI 兼容接口 |
| `ollama` | `openai-chat` | 默认本机 `http://127.0.0.1:11434/v1`，使用已安装模型名 |
| `custom` | 自选 | 兼容网关、其它服务商、LM Studio/vLLM 等兼容服务器 |

预设数据位于 `computer/providers.defaults.json`；模型名由你填写，不用“最新型号”替用户决定。Base URL 包含服务商要求的路径前缀，例如 `/v1` 或 `/compatible-mode/v1`，**不要再加 `/chat/completions` 或 `/responses`**。独有私有协议需要新增适配器及测试，不能靠换 Key 自动兼容。

**确认账号与地址匹配。** 同一厂商的按量 API、Coding Plan、地域和网关地址可能不同；预设不是套餐权益/免费额度证明。向导会要求确认 Base URL；不会检测套餐后自动改到按量接口，不因失败而切换厂商或模型。健康检查不调用付费 API。

## 最小配置

在仓库外创建 chmod-600 的 env 文件，例如选择 DeepSeek：

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=YOUR_ENABLED_MODEL
LLM_API_KEY=
ASR_PROVIDER=none
TTS_PROVIDER=none
SEARCH_PROVIDER=none
```

填写自己的 API 模型 ID 和 Key 后，运行 `sudo ./install.sh --apply --data-dir YOUR_DATA_DIRECTORY --hostname YOUR_DNS_OR_IP --env-file /private/provider.env`。日常推荐 `sudo ./install.sh --setup`，按向导选择服务商；Key 隐藏输入。

自定义兼容网关：

```dotenv
LLM_PROVIDER=custom
LLM_API_TYPE=openai-chat
LLM_BASE_URL=https://gateway.example/v1
LLM_MODEL=YOUR_ENABLED_MODEL
LLM_API_KEY=
```

`LLM_API_TYPE` 可选 `openai-chat`、`openai-responses`、`anthropic`、`minimax-messages`。MiniMax 原生协议限制为官方 origin；代理网关用相应兼容协议。云 API 必须 HTTPS；本机与明确私有 IP 的 HTTP 服务可以不提供 Key。没有“忽略证书”开关；不要为了本地模型开放公网无鉴权接口。

旧 `MINIMAX_MODEL`、`MINIMAX_API_HOST`、`MINIMAX_API_KEY` 保留读取兼容。新 `LLM_*` 优先；选择其它服务商不会继承旧 MiniMax Key 或主机地址。本地无鉴权模型不再因为 Key 为空而被判断成未配置。

## 语音与搜索单独选择

非 MiniMax 文本后端默认关闭附加服务，可先做网页文字聊天；ESP32 语音流程需要另外配置 ASR/TTS，首次身份创建仍按固件流程完成。比如 DeepSeek 负责思考，MiniMax 负责语音：

```dotenv
ASR_PROVIDER=minimax
ASR_MODEL=asr-1.0
ASR_API_KEY=
TTS_PROVIDER=minimax
TTS_MODEL=speech-2.8-turbo
TTS_API_KEY=
SEARCH_PROVIDER=none
```

也可分别用 `ASR_PROVIDER=openai-compatible` / `TTS_PROVIDER=openai-compatible`，各自设置 `ASR_BASE_URL` / `TTS_BASE_URL`、`ASR_API_KEY` / `TTS_API_KEY`、模型名。以提供 OpenAI 音频接口的服务为例：

```dotenv
ASR_PROVIDER=openai-compatible
ASR_BASE_URL=https://api.openai.com/v1
ASR_MODEL=whisper-1
ASR_API_KEY=
TTS_PROVIDER=openai-compatible
TTS_BASE_URL=https://api.openai.com/v1
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=alloy
TTS_API_KEY=
```

模型/音色只是接口配置示例，须确认所选服务实际提供。ASR 与 TTS 也可以来自不同厂商，不能因为提供了 Chat API 就假定它有音频接口。`none` 明确禁用能力，不会回退去调用其它服务。

仅当现有 MiniMax 对话后端与附加服务 **地址完全一致** 时，兼容旧部署共享该 Key。其它情况必须配置各自 Key；向导仅在用户选择相同地址并明确留空复用时复制 Key。独立的 `SEARCH_PROVIDER=minimax` 需要 `SEARCH_API_KEY`（和可选 `SEARCH_BASE_URL`）；目前内置搜索适配器为 MiniMax / none，电脑上的真实浏览器能力不依赖文本厂商的原生搜索接口。

板端音频协议保持 16kHz 单声道 PCM。MiniMax 流式仍直通；OpenAI 兼容 TTS 桥接先缓冲 PCM，按 `options.speech.openai_pcm_rate`（默认 24kHz）重采样为 16kHz，再交给网页/板子，**不是端到端实时语音**。其音色由 `TTS_VOICE`（或 `speech.openai_voice`）设置；板端内置 MiniMax 音色选择列表暂不映射其它厂商。

## 请求参数与验证范围

`options.llm` 中：`send_temperature` 默认 `auto`，可以 true/false；`effort_mode` 默认 `auto`，可设 `none` / `minimax` / `openai`；`token_parameter` 控制 Chat 的 `max_tokens` 或 `max_completion_tokens`。MiniMax 保留原有思考参数，其余预设默认不强加厂商特有参数。Responses 使用 `max_output_tokens`，Messages 使用 `max_tokens`。

流解析分别验证结束事件，拒绝截断/过滤/未处理的工具调用，不把 reasoning/thinking delta 当最终台词；取消会丢弃迟到结果。实际电脑执行仍需验证返回结果，原有权限与接管保护保持生效。文本 HTTP 请求禁止重定向，避免 Key 跟到另一个地址；普通任务进程不继承任何服务凭据。

自动测试验证真实本地 HTTP 的三类通用协议、流式终止、取消、模型名传递和凭据隔离，以及模拟音频接口；带 FFmpeg 的 Linux 测试验证重采样。**没有使用用户 Key 逐家进行付费调用**，不宣称所有厂商/型号/套餐都已实测。真实权限、速度、JSON/识图能力、语音准确率需要用部署者自己的模型验收。当前是文本/图片消息协议转换与独立 ASR/TTS，没有原生音频到音频对话适配器；没有因网页订阅而自动获得 API 权限。

协议依据：[OpenAI Chat 流事件](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)、[OpenAI Responses 流事件](https://developers.openai.com/api/docs/guides/streaming-responses)、[OpenAI 语音 PCM 格式](https://developers.openai.com/api/docs/guides/text-to-speech)、[Anthropic 流事件](https://platform.claude.com/docs/en/build-with-claude/streaming)、[DeepSeek 接入](https://api-docs.deepseek.com/guides/search_fetch)、[百炼地址](https://help.aliyun.com/zh/model-studio/base-url)、[方舟地址与鉴权](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en)、[Gemini 兼容接口](https://ai.google.dev/gemini-api/docs/openai)、[Ollama 兼容接口](https://docs.ollama.com/api/openai-compatibility)。
