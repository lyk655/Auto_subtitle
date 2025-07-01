import torch
from pathlib import Path
import time
import torchaudio
from moviepy import VideoFileClip
import torchaudio.transforms as T
import numpy as np
import soundfile as sf
import whisper
# demucs can be slow to import, so it's fine here
from demucs.pretrained import get_model
from demucs.apply import apply_model

# --- Your Subtitle Generation Function (get_subtitle) ---
def get_subtitle(video_path: str, progress_notification: ui.notification) -> Path:
    """
    Processes a video file to extract vocals and generate an SRT subtitle file.
    Args:
        video_path: Path to the input video file.
        progress_notification: A NiceGUI notification object to update with progress.
    Returns:
        Path to the generated SRT file, or None if failed.
    """
    try:
        output_dir = Path("demucs_output")
        output_dir.mkdir(exist_ok=True)
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {device}")

        # 1. Extract audio using moviepy
        progress_notification.message = '步骤 1/4: 正在提取音频...'
        print("Extracting audio from video...")
        with VideoFileClip(video_path) as video:
            audio = video.audio
            if audio is None:
                raise ValueError("视频文件中不包含音频。")
            # Using a temporary file can be more memory-efficient for large videos
            temp_audio_path = output_dir / f"{Path(video_path).stem}_audio.wav"
            audio.write_audiofile(str(temp_audio_path), codec='pcm_s16le')
        
        waveform, sr = torchaudio.load(temp_audio_path)
        temp_audio_path.unlink() # Clean up temporary audio file

        # 2. Separate vocals using Demucs
        progress_notification.message = '步骤 2/4: 正在分离人声 (这可能需要一些时间)...'
        print("Loading Demucs model...")
        model_name = "htdemucs"
        model = get_model(model_name).to(device)
        model.eval()

        # Resample if necessary
        if sr != model.samplerate:
            resampler = T.Resample(sr, model.samplerate).to(device)
            waveform = resampler(waveform)
        sr = model.samplerate
        
        # Demucs expects [batch, channels, samples]
        if waveform.dim() == 1: waveform = waveform.unsqueeze(0) # mono to stereo-like
        if waveform.dim() == 2: waveform = waveform.unsqueeze(0) # [channels, samples] to [batch, channels, samples]
        
        waveform = waveform.to(device)

        print("Applying Demucs model...")
        sources = apply_model(model, waveform, split=True, overlap=0.25, device=device)
        sources = sources.cpu()
        
        # Find vocals and save
        vocals_source = None
        for i, name in enumerate(model.sources):
            if name == "vocals":
                vocals_source = sources[0, i]
                break
        
        if vocals_source is None:
            raise RuntimeError("Demucs未能分离出人声音轨。")
            
        vocals_path = output_dir / "vocals.wav"
        print(f"Saving vocals to {vocals_path}...")
        sf.write(str(vocals_path), vocals_source.T.numpy(), sr)

        # 3. Transcribe with Whisper
        progress_notification.message = '步骤 3/4: 正在转录文本 (这也可能需要一些时间)...'
        print("Loading Whisper model...")
        # Use a smaller model for faster processing if needed, e.g., "base" or "small"
        whisper_model = whisper.load_model("medium", device=device)
        print("Transcribing vocals...")
        result = whisper_model.transcribe(str(vocals_path), language="zh", fp16=torch.cuda.is_available())

        # 4. Create SRT file
        progress_notification.message = '步骤 4/4: 正在生成SRT文件...'
        print("Creating SRT file...")
        srt_path = output_dir / "subtitle.srt"
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(result["segments"], 1):
                start, end, text = segment["start"], segment["end"], segment["text"].strip()
                def format_time(t):
                    h, m, s = int(t//3600), int((t%3600)//60), int(t%60)
                    ms = int((t - int(t)) * 1000)
                    return f"{h:02}:{m:02}:{s:02},{ms:03}"
                f.write(f"{i}\n{format_time(start)} --> {format_time(end)}\n{text}\n\n")
        
        print(f"SRT字幕已保存到: {srt_path}")
        return srt_path

    except Exception as e:
        print(f"生成字幕时发生错误: {e}")
        # Update the notification with the error message
        progress_notification.message = f'错误: {e}'
        progress_notification.type = 'negative'
        # Let it show for a while
        time.sleep(5)
        return None
    finally:
        # Close the persistent notification
        progress_notification.dismiss()
