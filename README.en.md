# Xiaoxi Companion · 小溪

[简体中文](README.md) | [English](README.en.md)

An open-source AI companion with a home, a memory, and a computer of her own.

Give Xiaoxi a name, call her over, and talk about your day. Ask her to look something up, draw a picture, set a reminder, or work on a task using her Linux computer. She lives on a small ESP32 screen, and you can also spend time with her in a web browser. Both share the same identity, memories, home, and task progress.

We're building a companion who gets to know you through everyday conversations, develops preferences over time, notices when she can help, and follows through on the work you give her. The project is actively evolving, and feedback from real use helps shape it.

## A look inside

![Xiaoxi's room, sample conversation, and workspace preview](docs/screenshots/home-and-chat.png)

These screenshots use sample conversations and an isolated demo workspace, with no real accounts or ESP32 device connected. You can also explore the [courtyard](docs/screenshots/courtyard.png), [Linux desktop](docs/screenshots/linux-desktop.png), and [private input form](docs/screenshots/private-input.png). See the [full gallery and capture notes](docs/screenshots/README.md).

## Spending time with Xiaoxi

- **Have a conversation.** Choose her name and use it to wake her locally. Talk by voice on the device, or use text and microphone input in the browser. Voice options depend on your speech service.
- **Get to know each other.** Xiaoxi organizes useful memories and preferences from your conversations, and learns reusable approaches from task results and feedback. You can choose her name, initial personality, and how she addresses you during the first meeting.
- **Visit her home.** She has a cozy room and courtyard inspired by traditional Chinese interiors, with places to rest, wash up, and work—and a cat to keep her company. Her location and activities stay in sync between the web and the ESP32 display.
- **Ask for help.** Set reminders, find information, generate images or videos, or send work to the Linux host. Media results are presented in a way that suits the current device. Reminders are routed preferentially to the device where you requested them.
- **See her computer.** With the optional desktop enabled, you can watch Xiaoxi use the browser and take control through noVNC. She combines page elements with screenshot-based visual grounding to locate controls, then checks the actual results. When a task needs an account or password, she can offer a private input form and continue after you fill it in.

The ESP32 device also supports Wi-Fi setup, battery and connection indicators, physical volume buttons, touch interactions, gravity-based screen rotation, and gradual dimming and screen-off behavior that adapts to battery or external power.

## How it fits together

```text
ESP32: display, mic, touch ------ HTTPS ---+
                                         +-- Linux host -- LLM / ASR / TTS
Web: home, chat, remote desktop - HTTPS ---+        |
                                                  +-- Your data directory
                                                  |   Memories, tasks, media, cache
                                                  +-- Dedicated desktop and browser
```

The ESP32 handles immediate interaction, audio recording and playback, and local wake-up detection. The Linux host handles model requests, memory, daily activity decisions, and task execution. The web interface brings her home, chat, and work desktop onto your computer. You choose where the data is stored.

## Getting started

Xiaoxi currently runs on an **RK3399 host paired with a Waveshare ESP32-S3-Touch-AMOLED-2.16**. The host installer targets Debian/Ubuntu with systemd, supports aarch64 and x86_64, and requires Python 3.11 or later. Other hardware, especially graphics drivers and the optional desktop, still needs platform-specific checks.

On the Linux machine that will run Xiaoxi, clone the repository and check the environment:

```sh
git clone https://github.com/gq3171/xiaoxi-companion.git
cd xiaoxi-companion
./install.sh --check --json
```

This check does not install packages or modify the system. When you're ready, start the setup wizard:

```sh
sudo ./install.sh --setup
```

Have these ready:

- A directory for Xiaoxi's data.
- A domain name or LAN IP address that your devices can reach.
- Your model provider, model name, API base URL, and API key.
- Speech service settings, if you want voice interaction.

The wizard provides presets for common providers and hides API keys as you enter them. It handles dependencies, native libraries and scene assets, service credentials, certificates, and startup checks.

You can use a separate drive or a regular directory, such as `/srv/fastdisk/xiaoxi`. If you provide a mount point, the installer uses a dedicated `xiaoxi` subdirectory beneath it. The host service, desktop, and maintenance tools share the saved path configuration.

**First-time setup still requires an ESP32 device to create Xiaoxi's identity and import it into the host before web chat becomes available.** A web-only onboarding flow is not available yet. The installer does not partition or format disks, configure your router, or flash the ESP32 automatically.

Detailed guides are currently in Chinese:

- [Host installation](docs/INSTALL.md)
- [Building and connecting the ESP32](firmware/README.md)
- [Deployment guide for coding agents](docs/INSTALL_FOR_AGENTS.md)

If you're using a coding agent to help with installation, ask it to read the deployment guide first. It explains which settings to ask you for, how to run the installer, and how to verify the result.

## Choosing models and voices

Xiaoxi supports MiniMax, Anthropic Messages, OpenAI Responses, and OpenAI-compatible Chat Completions. Provider presets include DeepSeek, Qwen, Doubao, Gemini, Ollama, and custom gateways.

Conversation, speech recognition, speech synthesis, and search are configured separately. You can use one model for reasoning and another service for speech. Check that the model, API endpoint, and permissions match your account and plan; protocol compatibility alone does not guarantee image or audio support.

Screenshot-based visual grounding requires a model that accepts images. For text-only models, set `options.desktop.browser_vision` to `false`; element-based browser tools remain available. Xiaoxi does not automatically switch to another paid provider.

See [model configuration](docs/MODELS.md) for examples and the tested scope, or [configuration reference](docs/CONFIGURATION.md) for all available settings. Both guides are currently in Chinese.

## Still a work in progress

Most of the current interface and detailed documentation are in Chinese. This English README introduces the project; it does not imply a fully localized English experience.

Voice responsiveness and recognition depend on the network, speech service, and surrounding sound. Local speaker verification remains experimental and should not be used to authorize high-risk actions.

Browser automation supports element-based targeting and screenshot-based visual grounding. Automated pixel control and dragging in arbitrary native Linux applications are not implemented yet. Complex websites, CAPTCHAs, and some actions still need your involvement. See the [desktop guide](docs/DESKTOP.md) for setup, handover, private input, and current limitations.

If something feels awkward, a task doesn't finish, or you have an idea for a new ability, please open an Issue. To contribute code, start with [development and testing](docs/DEVELOPMENT.md).

## License and privacy

Project code is released under the [MIT license](LICENSE). Third-party fonts, models, and noVNC retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

The repository does not include personal API keys, private certificates, Wi-Fi passwords, chat databases, or owner voiceprints. Keep your own credentials and runtime data in private deployment directories. See [security and privacy](SECURITY.md) for details.
