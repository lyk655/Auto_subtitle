# backend.py

import os
import asyncio
from pathlib import Path
import traceback
import json
import torch
import whisper
import torchaudio
import soundfile as sf
from openai import OpenAI
from moviepy import VideoFileClip
from demucs.pretrained import get_model
from demucs.apply import apply_model
from pyannote.audio import Pipeline

# --- 辅助函数 (保持不变) ---
def assign_speaker_to_whisper_segments(diarization_result, whisper_segments):
    # ... (此函数代码与您提供的版本相同，此处省略以保持简洁)
    speaker_timestamps = []
    for turn, _, speaker in diarization_result.itertracks(yield_label=True):
        speaker_timestamps.append({'start': turn.start, 'end': turn.end, 'speaker': speaker})
    for seg in whisper_segments:
        segment_center = seg.get('start', 0) + (seg.get('end', 0) - seg.get('start', 0)) / 2
        assigned_speaker = '未知'
        for turn in speaker_timestamps:
            if segment_center >= turn['start'] and segment_center <= turn['end']:
                assigned_speaker = turn['speaker']
                break
        seg['speaker'] = assigned_speaker
    return whisper_segments


class SubtitleGenerator:
    """
    集成了 Demucs, Pyannote, Whisper 和 LLM 优化的字幕生成器。
    模型在初始化时加载一次，专为后端服务设计。
    """
    def __init__(self, config: dict):
        self.conf = config
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"字幕生成器使用设备: {self.device}")

        # --- 从配置中设置环境变量 (必须在导入 huggingface 库之前) ---
        if self.conf.get('hf_cache_dir'):
            hf_cache_path = Path(self.conf['hf_cache_dir'])
            hf_cache_path.mkdir(parents=True, exist_ok=True)
            os.environ['HF_HOME'] = str(hf_cache_path)
            print(f"Hugging Face 缓存路径设置为: {hf_cache_path}")

        if not self.conf.get('hf_token'):
            raise ValueError("Hugging Face Token 未在配置中提供，无法加载 Pyannote 模型。")
        
        print("正在加载所有模型，应用启动可能需要一些时间...")
        self.demucs_model = get_model("htdemucs").to(self.device)
        self.demucs_model.eval()

        whisper_model_name = self.conf.get('model_name', "large-v3")
        self.whisper_model = whisper.load_model(whisper_model_name, device=self.device)
        
        self.diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=self.conf['hf_token']
        ).to(torch.device(self.device))

        self.llm_client = None
        if self.conf.get('use_deepseek') and self.conf.get('deepseek_api_key'):
            try:
                self.llm_client = OpenAI(api_key=self.conf['deepseek_api_key'], base_url="https://api.deepseek.com")
                print("DeepSeek 客户端初始化成功。")
            except Exception as e:
                print(f"警告: 初始化 DeepSeek 客户端失败: {e}")
        
        print("所有模型加载完毕，服务已就绪。")

    def _optimize_with_llm(self, segments: list) -> list:
        # ... (此函数代码与您提供的版本相同，此处省略以保持简洁)
        if not self.llm_client or not segments: return segments
        print(f"正在向 DeepSeek 发送 {len(segments)} 条字幕进行批量优化...")
        original_texts = [seg['text'] for seg in segments]
        prompt_content = """你是一个专业的字幕校对员。用户会提供一个JSON数组，其中包含由ASR生成的、可能存在识别错误且未加标点的句子。
你的任务是：
1. 逐句修正文本中的谐音或识别错误。
2. 为每句话添加恰当的标点符号，使其通顺易读。
3. 以一个JSON数组的形式返回处理后的结果，数组长度必须与输入完全一致。
4. 不要合并或拆分句子，保持原始句子的数量。
5. 只返回JSON数组，不要包含任何额外的解释或代码块标记。

示例输入: ["how are you today", "im fine thank you"]
示例输出: ["How are you today?", "I'm fine, thank you."]

示例输入: ["今天天气真好我们去公园玩吧", "那里有很多花草"]
示例输出: ["今天天气真好，我们去公园玩吧。", "那里有很多花草。"]
"""
        system_prompt = {"role": "system", "content": prompt_content}
        user_prompt = {"role": "user", "content": json.dumps(original_texts, ensure_ascii=False)}
        try:
            response = self.llm_client.chat.completions.create(model="deepseek-chat", messages=[system_prompt, user_prompt], stream=False, temperature=0.2)
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"): content = content[7:-4]
            if content.startswith("`"): content = content.strip("`")
            optimized_texts = json.loads(content)
            if isinstance(optimized_texts, list) and len(optimized_texts) == len(segments):
                for i, seg in enumerate(segments):
                    if isinstance(optimized_texts[i], str) and optimized_texts[i].strip():
                        seg['text'] = optimized_texts[i]
                print("DeepSeek 批量优化成功。")
                return segments
            else:
                print(f"警告: DeepSeek 返回格式不匹配 (返回 {len(optimized_texts)} 条, 预期 {len(segments)} 条)，将使用原始文本。")
        except Exception as e:
            print(f"调用 DeepSeek API 或解析结果失败，将使用原始文本: {e}")
            traceback.print_exc()
        return segments


    def run(self, video_path: str, language: str = None, num_speakers: int = None, progress_handler=None) -> str:
        # ... (此函数代码与您提供的版本相同，逻辑非常稳健，无需修改)
        # ... (此处省略以保持简洁)
        output_dir = Path("demucs_output")
        output_dir.mkdir(exist_ok=True)
        def update_progress(message: str):
            if progress_handler: progress_handler(message)
            print(f"进度: {message}")
        try:
            update_progress("步骤 1/7: 提取音频...")
            with VideoFileClip(video_path) as video:
                if video.audio is None: raise ValueError("视频文件不含音频。")
                temp_audio_path = output_dir / f"{Path(video_path).stem}_audio.wav"
                video.audio.write_audiofile(str(temp_audio_path), codec='pcm_s16le', logger=None)
            waveform, sr = torchaudio.load(temp_audio_path)
            update_progress("步骤 2/7: 分离人声 (Demucs)...")
            if sr != self.demucs_model.samplerate:
                waveform = torchaudio.transforms.Resample(sr, self.demucs_model.samplerate)(waveform)
            sr = self.demucs_model.samplerate
            if waveform.dim() == 1: waveform = waveform.unsqueeze(0)
            if waveform.dim() > 2: waveform = waveform.mean(dim=0, keepdim=True)
            sources = apply_model(self.demucs_model, waveform.to(self.device).unsqueeze(0), split=True, device=self.device)
            vocals_source = sources[0, self.demucs_model.sources.index("vocals")].cpu()
            vocals_path = output_dir / f"{Path(video_path).stem}_vocals.wav"
            sf.write(str(vocals_path), vocals_source.T.numpy(), sr)
            temp_audio_path.unlink()
            update_progress("步骤 3/7: 识别说话人 (Pyannote)...")
            diarization_params = {}
            if num_speakers and num_speakers > 0:
                diarization_params['num_speakers'] = num_speakers
                update_progress(f"步骤 3/7: 识别说话人 (Pyannote，指定 {num_speakers} 人)...")
            else:
                # 如果不指定人数，可以给一个范围提示，这比完全自动检测要好
                # diarization_params['min_speakers'] = 2
                # diarization_params['max_speakers'] = 5
                update_progress("步骤 3/7: 识别说话人 (Pyannote，自动检测人数)...")
            diarization_result = self.diarization_pipeline(str(vocals_path), **diarization_params)
            update_progress("步骤 4/7: 转录文本 (Whisper)...")
            whisper_result = self.whisper_model.transcribe(str(vocals_path), language=language, fp16=torch.cuda.is_available())
            vocals_path.unlink()
            if not whisper_result.get("segments"): raise ValueError("Whisper 未检测到任何语音片段。")
            update_progress("步骤 5/7: 匹配说话人与文本...")
            final_segments = assign_speaker_to_whisper_segments(diarization_result, whisper_result["segments"])
            if self.llm_client and self.conf.get('use_deepseek', False):
                update_progress("步骤 6/7: DeepSeek 润色...")
                final_segments = self._optimize_with_llm(final_segments)
            update_progress("步骤 7/7: 生成 SRT 文件...")
            srt_path = output_dir / f"{Path(video_path).stem}_subtitle.srt"
            with open(srt_path, "w", encoding="utf-8") as f:
                def format_time(t):
                    if t is None or not isinstance(t, (int, float)): return "00:00:00,000"
                    h, rem = divmod(t, 3600); m, s = divmod(rem, 60); ms = int((s - int(s)) * 1000)
                    return f"{int(h):02}:{int(m):02}:{int(s):02},{ms:03}"
                for i, segment in enumerate(final_segments):
                    text = segment.get('text', '').strip()
                    if not text: continue
                    f.write(f"{i + 1}\n")
                    f.write(f"{format_time(segment.get('start'))} --> {format_time(segment.get('end'))}\n")
                    speaker = segment.get('speaker', '未知')
                    f.write(f"{speaker}: {text}\n\n")
            update_progress("完成！")
            return str(srt_path)
        except Exception as e:
            traceback.print_exc()
            update_progress(f"错误: {e}")
            if 'vocals_path' in locals() and locals()['vocals_path'].exists():
                locals()['vocals_path'].unlink()
            raise e

# 移除模块级别的单例创建和本地测试入口
# 这些职责将移交给 main.py 和专门的测试脚本