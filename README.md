# 自动字幕生成器

本项目是一个基于 AI 的自动视频字幕生成与编辑工具，集成了 OpenAI Whisper、Pyannote、Demucs 等模型，支持多说话人分离、字幕润色，并提供了现代化的 NiceGUI 前端界面，适合内容创作者、字幕组、教育等场景。

## 功能特性

- **自动提取视频音频并转文字**：支持多种视频格式，自动提取音频并识别为文本。
- **多说话人分离**：集成 Pyannote，实现说话人分离与标注。
- **字幕润色**：可选接入 DeepSeek LLM，对字幕文本进行自动校对和标点优化。
- **SRT 字幕导出**：一键生成标准 SRT 字幕文件，支持下载和二次编辑。
- **可视化前端**：基于 NiceGUI，支持视频上传、参数配置、字幕预览与编辑。
- **多模型支持**：Whisper 多种模型可选，兼容 Hugging Face Token 配置。

## 安装与环境准备

建议使用 Conda 环境：

```bash
conda create -n subtitle python=3.9 -y
conda activate subtitle
pip install -r requirements.txt
```

## 快速开始

1. **配置 Hugging Face Token**  
   运行后首次进入“设置”页面，填写 Hugging Face Token（用于下载 Pyannote 模型），可选填写 DeepSeek API Key 以启用字幕润色。

2. **启动服务**  
   ```bash
   python main.py
   ```
   默认前端地址为 [http://localhost:8082](http://localhost:8082)

3. **使用流程**  
   - 上传视频文件
   - 选择识别语言、说话人数（可选）
   - 点击“生成字幕”，等待处理完成
   - 预览、编辑字幕并导出 SRT 文件

## 依赖说明

详见 `requirements.txt`，主要依赖包括：

- [OpenAI Whisper](https://github.com/openai/whisper)
- [Pyannote-audio](https://github.com/pyannote/pyannote-audio)
- [Demucs](https://github.com/facebookresearch/demucs)
- [NiceGUI](https://github.com/zauberzeug/nicegui)
- 以及相关音频、视频处理库

## 配置文件

- `config.json`：存储模型选择、API Token 等配置信息
- 支持自定义 Hugging Face 缓存目录，便于多环境部署

## 目录结构

```
├── main.py              # 启动入口，负责前后端集成
├── webui.py             # NiceGUI 前端页面与交互逻辑
├── get_subtitle.py      # 字幕生成核心流程（音频分离、识别、分离、润色、SRT导出）
├── utils.py             # 工具函数与数据结构
├── config.py            # 配置加载与校验
├── requirements.txt     # 依赖列表
├── config.json          # 用户配置
├── cache/               # 视频与中间文件缓存目录
├── demucs_output/       # Demucs 音频分离输出
└── README.md            # 项目说明
```

## 常见问题

- **模型下载慢/失败**：建议配置 Hugging Face Token，并可自定义缓存目录。
- **显卡支持**：优先使用 CUDA，如无 GPU 自动切换 CPU，但速度会变慢。
- **DeepSeek 润色可选**：如无需求可不填写 API Key。

## TODO

- 支持更多字幕格式导出
- 增强字幕编辑功能
- 支持批量处理与命令行模式