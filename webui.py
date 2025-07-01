import tempfile
from pathlib import Path
from dataclasses import dataclass
import pysrt
import asyncio
from nicegui import app, ui
from typing import Union
from nicegui.events import UploadEventArguments
import time

import torch
import torchaudio
from moviepy import VideoFileClip
import torchaudio.transforms as T
import numpy as np
import soundfile as sf
import whisper
from demucs.pretrained import get_model
from demucs.apply import apply_model


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


# --- NiceGUI App Code (with modifications) ---

@dataclass
class Subtitle:
    id: int
    pysrt_item: pysrt.SubRipItem
    @property
    def start(self): return self.pysrt_item.start.to_time()
    @property
    def end(self): return self.pysrt_item.end.to_time()
    @property
    def text(self): return self.pysrt_item.text

def load_srt_to_subs(srt_path: Path) -> list[Subtitle]:
    subs_list = []
    if not srt_path or not srt_path.exists():
        ui.notify(f"字幕文件不存在: {srt_path}", type='negative')
        return subs_list
    try:
        srt_file = pysrt.open(str(srt_path), encoding='utf-8')
        for i, pysrt_item in enumerate(srt_file):
            subs_list.append(Subtitle(id=i, pysrt_item=pysrt_item))
        ui.notify(f'成功加载 {len(subs_list)} 条字幕。', type='positive')
    except Exception as e:
        ui.notify(f"加载SRT文件时出错: {e}", type='negative')
    return subs_list

@ui.page('/')
def main_page():
    @dataclass
    class AppState:
        video_path: Union[Path, None] = None
        subtitles: list[Subtitle] = None
        selected_sub: Union[Subtitle, None] = None

    state = AppState()
    temp_dir = Path(tempfile.gettempdir())

    with ui.header(elevated=True).classes('justify-between'):
        ui.label('电影字幕生成器').classes('text-2xl')
        with ui.row():
            video_uploader = ui.upload(on_upload=lambda e: handle_upload(e), auto_upload=True).props('accept="video/*"').style('width:0; height:0; overflow:hidden;')
            upload_button = ui.button('上传视频', on_click=lambda: video_uploader.run_method('pickFiles'), icon='movie')
            save_button = ui.button('保存字幕文件', on_click=lambda: download_srt(), icon='save')

    with ui.grid(columns=2).classes('w-full p-4 gap-4'):
        with ui.column().classes('w-full'):
            with ui.element('div').classes('relative w-full aspect-video bg-black flex items-center justify-center rounded-lg overflow-hidden') as video_container:
                ui.label('上传视频以开始').classes('text-2xl text-gray-400')
                video: ui.video = None
                subtitle_label = ui.label('').classes(
                    'absolute text-white font-bold text-2xl text-center w-full transition-all duration-100 hidden'
                ).style(
                    'bottom: 20px; left: 50%; transform: translateX(-50%); text-shadow: 2px 2px 4px black;'
                )

        with ui.column().classes('w-full'):
            ui.label('字幕').classes('text-xl font-semibold')
            with ui.card().classes('w-full h-[40vh] p-0'):
                table = ui.table(
                    columns=[
                        {'name': 'id', 'label': 'ID', 'field': 'id', 'sortable': True, 'classes': 'w-1/12'},
                        {'name': 'start', 'label': '开始时间', 'field': 'start', 'sortable': True, 'classes': 'w-3/12'},
                        {'name': 'end', 'label': '结束时间', 'field': 'end', 'sortable': True, 'classes': 'w-3/12'},
                        {'name': 'text', 'label': '内容', 'field': 'text', 'align': 'left', 'classes': 'w-5/12'}
                    ],
                    rows=[], row_key='id', selection='single', on_select=lambda e: handle_select(e.selection)
                ).classes('w-full h-full')

            with ui.card().classes('w-full mt-4') as edit_card:
                ui.label('编辑字幕').classes('text-xl font-semibold')
                start_input = ui.input('开始时间 (hh:mm:ss,ms)')
                end_input = ui.input('结束时间 (hh:mm:ss,ms)')
                text_input = ui.textarea('内容').props('autogrow')
                ui.button('应用更改', on_click=lambda: apply_changes())

    edit_card.visible = False
    save_button.set_visibility(False)

    # --- THIS IS THE CORE OF THE CHANGE ---
    async def handle_upload(e: UploadEventArguments):
        nonlocal video, subtitle_label
        
        # Save the uploaded file to a temporary directory
        file_path = temp_dir / e.name
        with open(file_path, 'wb') as f: f.write(e.content.read())
        state.video_path = file_path

        # Clear UI and prepare for loading state
        upload_button.disable()
        table.rows.clear()
        table.update()
        save_button.set_visibility(False)
        video_container.clear()
        with video_container:
            video = ui.video(f'/video/{state.video_path.name}').classes('w-full')
            subtitle_label = ui.label('').classes(
                'absolute text-white font-bold text-2xl text-center w-full transition-all duration-100 hidden'
            ).style(
                'bottom: 20px; left: 50%; transform: translateX(-50%); text-shadow: 2px 2px 4px black;'
            )
            spinner = ui.spinner(size='lg', color='white').classes('absolute')

        # Show a persistent notification for progress
        progress_notification = ui.notification(
            '准备开始生成字幕...', position='bottom-right', close_button='OK', timeout=None
        )

        srt_path = None
        try:
            # Run the blocking function in a separate thread
            loop = asyncio.get_running_loop()
            srt_path = await loop.run_in_executor(
                None, get_subtitle, str(state.video_path), progress_notification
            )
        except Exception as ex:
            ui.notify(f"处理时发生意外错误: {ex}", type='negative')
        finally:
            # This block will run whether an error occurred or not
            spinner.delete()
            upload_button.enable()

        # Load subtitles if generation was successful
        if srt_path and srt_path.exists():
            state.subtitles = load_srt_to_subs(srt_path)
            table.rows = [{'id': s.id, 'start': str(s.start), 'end': str(s.end), 'text': s.text} for s in state.subtitles]
            save_button.set_visibility(True)
            ui.notify('字幕生成完毕!', type='positive')
        else:
            ui.notify('字幕生成失败，请查看控制台日志。', type='negative')

    def handle_select(selection: list):
        # ... (no changes needed here)
        if not selection:
            state.selected_sub = None
            edit_card.visible = False
            return
        row = selection[0]
        sub = next((s for s in state.subtitles if s.id == row['id']), None)
        if sub:
            state.selected_sub = sub
            edit_card.visible = True
            start_input.value, end_input.value, text_input.value = str(sub.pysrt_item.start), str(sub.pysrt_item.end), sub.text
            if video: video.seek(sub.pysrt_item.start.ordinal / 1000); video.play()

    def apply_changes():
        # ... (no changes needed here)
        sub = state.selected_sub
        if not sub: return
        try:
            sub.pysrt_item.start.from_string(start_input.value)
            sub.pysrt_item.end.from_string(end_input.value)
            sub.pysrt_item.text = text_input.value
            for row in table.rows:
                if row['id'] == sub.id: row['start'], row['end'], row['text'] = str(sub.start), str(sub.end), sub.text; break
            table.update(); ui.notify('更改已应用！', type='positive')
        except Exception as e: ui.notify(f'时间格式无效: {e}', type='negative')

    def download_srt():
        # ... (no changes needed here)
        if not state.subtitles: return
        final_srt = pysrt.SubRipFile([sub.pysrt_item for sub in state.subtitles])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write(str(final_srt))
            ui.download(f.name, filename='edited_subtitles.srt')
        ui.notify('字幕文件即将开始下载。', type='positive')

if __name__ in {"__main__", "__mp_main__"}:
    app.add_static_files('/video', tempfile.gettempdir())
    # You might want to expose the output directory as well for debugging
    app.add_static_files('/output', 'demucs_output') 
    ui.run(title='字幕编辑器', uvicorn_reload_dirs=str(Path(__file__).parent), port=8081)