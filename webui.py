import tempfile
from pathlib import Path
import pysrt
import asyncio
from nicegui import app, ui
from nicegui.events import UploadEventArguments
from backend.get_subtitle import get_subtitle
from utils import load_srt_to_subs,AppState


# --- NiceGUI App Code (with modifications) ---

@ui.page('/')
def main_page():
    
    state = AppState()
    temp_dir = Path(tempfile.gettempdir())

    with ui.header(elevated=True).classes('justify-between'):
        ui.label('电影字幕生成器').classes('text-2xl')
        with ui.row():
            video_uploader = ui.upload(on_upload=lambda e: handle_upload(e), auto_upload=True).props(
                'accept="video/*"').style('width:0; height:0; overflow:hidden;')
            upload_button = ui.button(
                '上传视频', on_click=lambda: video_uploader.run_method('pickFiles'), icon='movie')
            save_button = ui.button(
                '保存字幕文件', on_click=lambda: download_srt(), icon='save')

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
                        {'name': 'id', 'label': 'ID', 'field': 'id',
                            'sortable': True, 'classes': 'w-1/12'},
                        {'name': 'start', 'label': '开始时间', 'field': 'start',
                            'sortable': True, 'classes': 'w-3/12'},
                        {'name': 'end', 'label': '结束时间', 'field': 'end',
                            'sortable': True, 'classes': 'w-3/12'},
                        {'name': 'text', 'label': '内容', 'field': 'text',
                            'align': 'left', 'classes': 'w-5/12'}
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

   
    async def handle_upload(e: UploadEventArguments):
        nonlocal video, subtitle_label

        # Save the uploaded file to a temporary directory
        file_path = temp_dir / e.name
        with open(file_path, 'wb') as f:
            f.write(e.content.read())
        state.video_path = file_path

        # Clear UI and prepare for loading state
        upload_button.disable()
        table.rows.clear()
        table.update()
        save_button.set_visibility(False)
        video_container.clear()
        with video_container:
            video = ui.video(
                f'/video/{state.video_path.name}').classes('w-full')
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
                None, get_subtitle, str(
                    state.video_path), progress_notification
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
            table.rows = [{'id': s.id, 'start': str(s.start), 'end': str(
                s.end), 'text': s.text} for s in state.subtitles]
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
            start_input.value, end_input.value, text_input.value = str(
                sub.pysrt_item.start), str(sub.pysrt_item.end), sub.text
            if video:
                video.seek(sub.pysrt_item.start.ordinal / 1000)
                video.play()

    def apply_changes():
        # ... (no changes needed here)
        sub = state.selected_sub
        if not sub:
            return
        try:
            sub.pysrt_item.start.from_string(start_input.value)
            sub.pysrt_item.end.from_string(end_input.value)
            sub.pysrt_item.text = text_input.value
            for row in table.rows:
                if row['id'] == sub.id:
                    row['start'], row['end'], row['text'] = str(
                        sub.start), str(sub.end), sub.text
                    break
            table.update()
            ui.notify('更改已应用！', type='positive')
        except Exception as e:
            ui.notify(f'时间格式无效: {e}', type='negative')

    def download_srt():
        # ... (no changes needed here)
        if not state.subtitles:
            return
        final_srt = pysrt.SubRipFile(
            [sub.pysrt_item for sub in state.subtitles])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write(str(final_srt))
            ui.download(f.name, filename='edited_subtitles.srt')
        ui.notify('字幕文件即将开始下载。', type='positive')