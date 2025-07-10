# webui.py

import tempfile
from pathlib import Path
import pysrt
import asyncio
import traceback
from typing import List, Dict
from functools import partial  # <<< 核心改动 1: 导入 partial

from nicegui import app, ui, context, Client
from nicegui.events import UploadEventArguments

# 确保从你的 utils 和 config 模块正确导入
from utils import load_srt_to_subs, AppState, group_subs_into_blocks, Sub
from config import save_config, get_config

CACHE_DIR = Path('./cache')
if not CACHE_DIR.exists():
    CACHE_DIR.mkdir()

DEMO_VIDEO_PATH = CACHE_DIR / 'demo.mp4'
    
SPEAKER_COLORS = ['red', 'orange', 'amber', 'lime', 'green', 'teal', 'cyan', 'indigo', 'purple']

def main_page(subtitle_generator, app_config):
    ui.dark_mode().enable()

    if not subtitle_generator:
        with ui.column().classes('w-full h-screen flex items-center justify-center'):
            ui.label('后端服务启动失败!').classes('text-2xl text-negative')
            ui.label('请先前往“设置”页面完成必要配置。').classes('text-lg')
            ui.button('前往设置', on_click=lambda: ui.navigate.to('/settings')).classes('mt-4')
        return

    app.storage.user['state'] = AppState()
    state: AppState = app.storage.user['state']
    
    ui_elements: Dict[str, ui.element] = {}

    async def rename_speaker_dialog(old_name: str):
        with ui.dialog() as dialog, ui.card():
            ui.label(f"重命名说话人: {old_name}").classes('text-lg font-bold')
            new_name_input = ui.input("新名称").props('autofocus outlined')
            
            async def apply_rename():
                new_name = new_name_input.value.strip()
                if not new_name or new_name == old_name:
                    ui.notify("新名称不能为空或与旧名称相同。", type='warning')
                    return
                modified_count = 0
                for sub in state.subtitles:
                    if sub.speaker == old_name:
                        sub.speaker = new_name
                        sub.pysrt_item.text = f"{new_name}: {sub.text}"
                        modified_count += 1
                ui.notify(f"成功将 '{old_name}' 的 {modified_count} 条字幕重命名为 '{new_name}'。", type='positive')
                dialog.submit('renamed')

            with ui.row().classes('w-full justify-end mt-4'):
                ui.button('取消', on_click=dialog.close)
                ui.button('保存', on_click=apply_rename, color='primary')

        result = await dialog
        if result == 'renamed':
            await redraw_views()

    async def edit_sub_dialog(sub: Sub):
        with ui.dialog() as dialog, ui.card().style('min-width: 600px'):
            ui.label('编辑字幕').classes('text-xl font-bold mb-4')
            unique_speakers = sorted(list(set(s.speaker for s in state.subtitles if s.speaker != '未知')))
            initial_speaker_value = sub.speaker if sub.speaker in unique_speakers else None
            new_speaker_input = ui.input("新说话人 (可选)").props('outlined dense')
            with ui.row().classes('w-full'):
                speaker_select = ui.select(unique_speakers, label='分配给已有说话人', value=initial_speaker_value, clearable=True).classes('flex-grow')
            start_input = ui.input('开始时间', value=str(sub.start))
            end_input = ui.input('结束时间', value=str(sub.end))
            text_area = ui.textarea('内容', value=sub.text).props('autogrow outlined')
            with ui.row().classes('w-full justify-end mt-4'):
                def apply_and_close():
                    try:
                        final_speaker = new_speaker_input.value.strip() or speaker_select.value or "未知"
                        sub.speaker = final_speaker
                        sub.start.from_string(start_input.value)
                        sub.end.from_string(end_input.value)
                        sub.text = text_area.value.strip()
                        sub.pysrt_item.start = sub.start
                        sub.pysrt_item.end = sub.end
                        sub.pysrt_item.text = f"{sub.speaker}: {sub.text}"
                        dialog.submit('ok')
                    except Exception as e:
                        ui.notify(f"格式错误或无效输入: {e}", type='negative')
                ui.button('取消', on_click=dialog.close)
                ui.button('保存', on_click=apply_and_close, icon='save')
        
        result = await dialog
        if result == 'ok':
            await redraw_views()

    async def redraw_views():
        if not state.subtitles: return

        table = ui_elements.get('table')
        if table:
            table.rows = [{'id': s.id, 'speaker': s.speaker, 'start': str(s.start), 'end': str(s.end), 'text': s.text} for s in state.subtitles]
            table.update()
        
        dialogue_container = ui_elements.get('dialogue_container')
        if dialogue_container:
            all_speaker_blocks = group_subs_into_blocks(state.subtitles)
            dialogue_container.clear()
            with dialogue_container:
                if not all_speaker_blocks:
                    ui.label("未能加载对话内容。").classes('text-center text-gray-500 p-4')
                    return
                speaker_color_map = {}
                color_index = 0
                for block in all_speaker_blocks:
                    if block.speaker not in speaker_color_map:
                        speaker_color_map[block.speaker] = SPEAKER_COLORS[color_index % len(SPEAKER_COLORS)]
                        color_index += 1
                    color = speaker_color_map[block.speaker]
                    with ui.column().classes('w-full gap-2 mb-4'):
                        # <<< 核心改动 2: 使用 functools.partial 绑定点击事件 >>>
                        ui.chip(block.speaker, icon='person', color=color).classes('font-bold cursor-pointer') \
                            .on('click', partial(rename_speaker_dialog, block.speaker))
                        
                        for sub in block.subs:
                            # <<< 核心改动 3: 对这里也使用 partial 以保持一致和稳定 >>>
                            with ui.row().classes('w-full items-start cursor-pointer hover:bg-slate-700 rounded-md p-2 transition-colors') \
                                .on('click', partial(edit_sub_dialog, sub)):
                                ui.label(f"{sub.start.minutes:02}:{sub.start.seconds:02}").classes('w-16 text-xs text-gray-400 pt-1')
                                ui.label(sub.text).classes('flex-grow text-sm')

    async def load_demo_video():
        if not DEMO_VIDEO_PATH.exists():
            ui.notify(f"演示视频未找到: {DEMO_VIDEO_PATH}。请放置一个 'demo.mp4' 文件在 cache 目录中。", type='negative')
            return
        
        generate_button.props('disable')
        save_button.props('disable')
        if ui_elements.get('dialogue_container'): ui_elements['dialogue_container'].clear()
        if ui_elements.get('table'): ui_elements['table'].rows.clear(); ui_elements['table'].update()

        state.video_path = DEMO_VIDEO_PATH
        video_container = ui_elements['video_container']
        video_container.clear()
        with video_container:
            ui.video(f'/video/{state.video_path.name}').classes('w-full h-full')
        
        ui.notify('演示视频加载成功！', type='positive')
        generate_button.props(remove='disable')

    async def handle_upload(e: UploadEventArguments, *, client: Client):
        with client:
            generate_button.props('disable')
            save_button.props('disable')
            if ui_elements.get('dialogue_container'): ui_elements['dialogue_container'].clear()
            if ui_elements.get('table'): ui_elements['table'].rows.clear(); ui_elements['table'].update()
            
            video_path = CACHE_DIR / e.name
            upload_notification = ui.notification(f"正在上传 {e.name}...", spinner=True, timeout=None, position='bottom-right')
        
            try:
                CHUNK_SIZE = 1024 * 1024 * 4
                with open(video_path, 'wb') as f:
                    while True:
                        chunk = await asyncio.to_thread(e.content.read, CHUNK_SIZE)
                        if not chunk: break
                        await asyncio.to_thread(f.write, chunk)
                
                state.video_path = video_path
                video_container = ui_elements['video_container']
                video_container.clear()
                with video_container:
                    ui.video(f'/video/{state.video_path.name}').classes('w-full h-full')
                    
                upload_notification.dismiss()
                ui.notify(f"视频 '{e.name}' 上传成功！", type='positive')
                generate_button.props(remove='disable')
                
            except Exception as ex:
                traceback.print_exc()
                upload_notification.dismiss()
                ui.notify(f"文件上传失败: {ex}", type='negative')
                if video_path.exists(): video_path.unlink()

    async def generate_subtitles():
        if not state.video_path:
            ui.notify("请先上传一个视频。", type='warning'); return
            
        generate_button.props('disable'); upload_button.props('disable')
        progress_notification = ui.notification('准备开始...', position='bottom-right', timeout=None, multi_line=True, spinner=True)
        
        try:
            def update_progress(msg: str):
                if progress_notification: progress_notification.message = msg

            loop = asyncio.get_running_loop()
            srt_path_str = await loop.run_in_executor(
                None, subtitle_generator.run, 
                str(state.video_path),
                language_select.value if language_select.value != 'auto' else None,
                int(num_speakers_input.value),
                update_progress
            )

            if srt_path_str and Path(srt_path_str).exists():
                ui.notify('SRT文件已生成，正在解析...', type='info')
                state.subtitles = load_srt_to_subs(srt_path_str)
                if not state.subtitles:
                    ui.notify('警告: SRT文件解析成功，但内容为空！', type='warning')
                
                await redraw_views()
                save_button.props(remove='disable')
                progress_notification.dismiss()
                ui.notify('字幕处理完毕!', type='positive')
            else:
                progress_notification.dismiss()
                ui.notify(f'字幕生成失败: 未找到SRT文件。', type='negative', multi_line=True)
        except Exception as ex:
            traceback.print_exc()
            progress_notification.dismiss()
            ui.notify(f"处理时发生意外错误: {ex}", type='negative', multi_line=True)
        finally:
            generate_button.props(remove='disable'); upload_button.props(remove='disable')

    def download_srt():
        if not state.subtitles:
            ui.notify("没有字幕可以保存。", type='warning'); return
        for sub in state.subtitles:
            sub.pysrt_item.text = f"{sub.speaker}: {sub.text}"
            sub.pysrt_item.start = sub.start
            sub.pysrt_item.end = sub.end
        final_srt = pysrt.SubRipFile([sub.pysrt_item for sub in sorted(state.subtitles, key=lambda s: s.start)])
        final_srt.clean_indexes()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write(str(final_srt)); temp_srt_path = f.name
        ui.download(temp_srt_path, filename=f'{state.video_path.stem}_edited.srt')

    # --- UI 布局 ---
    with ui.header(elevated=True).classes('bg-slate-800 justify-between px-4'):
        with ui.row(align_items='center'):
            ui.icon('subtitles', size='lg', color='white')
            ui.label('AI 字幕工作台').classes('text-xl font-bold')
        with ui.row(align_items='center', wrap=False).classes('gap-2'):
            num_speakers_input = ui.number(label='说话人数', value=0, min=0, format='%d').props('dense outlined dark').style('width: 120px;')
            language_select = ui.select(options={'auto': '自动检测', 'zh': '中文', 'en': '英文'}, label='识别语言', value='auto').props('dense outlined dark').style('width: 150px;')
            
            video_uploader = ui.upload(
                on_upload=lambda e: asyncio.create_task(handle_upload(e, client=context.client)), 
                auto_upload=True
            ).props('accept="video/*"').style('width:0; height:0; overflow:hidden;')

            upload_button = ui.button('加载视频', on_click=lambda: video_uploader.run_method('pickFiles'), icon='movie', color='primary')
            ui.button('加载演示', on_click=load_demo_video, icon='play_circle_outline').tooltip('加载服务器 cache/demo.mp4 文件')
            generate_button = ui.button('生成字幕', on_click=generate_subtitles, icon='auto_fix_high').props('disable')
            save_button = ui.button('保存 SRT', on_click=download_srt, icon='save').props('disable')
            ui.link('设置', '/settings').classes('text-white')

    with ui.splitter(value=50).classes('w-full h-screen-minus-header bg-slate-900') as splitter:
        with splitter.before:
            with ui.column().classes('w-full h-full p-4 gap-4'):
                ui_elements['video_container'] = ui.element('div').classes('relative w-full aspect-video bg-black flex items-center justify-center rounded-lg overflow-hidden shadow-lg')
                with ui_elements['video_container']:
                    ui.label('请上传视频').classes('text-2xl text-gray-600')

        with splitter.after:
            with ui.column().classes('w-full h-full no-wrap'):
                with ui.tabs().classes('w-full') as tabs:
                    dialogue_tab = ui.tab('对话', icon='groups')
                    table_tab = ui.tab('表格', icon='table_rows')
                
                with ui.tab_panels(tabs, value=dialogue_tab).classes('w-full flex-grow bg-slate-800'):
                    with ui.tab_panel(dialogue_tab).classes('p-0'):
                        with ui.column().classes('w-full h-full overflow-y-auto p-4'):
                            ui_elements['dialogue_container'] = ui.column().classes('w-full gap-2')
                    
                    with ui.tab_panel(table_tab).classes('p-0'):
                        ui_elements['table'] = ui.table(
                            columns=[
                                {'name': 'id', 'label': 'ID', 'field': 'id'},
                                {'name': 'speaker', 'label': '说话人', 'field': 'speaker', 'sortable': True},
                                {'name': 'start', 'label': '开始', 'field': 'start', 'sortable': True},
                                {'name': 'end', 'label': '结束', 'field': 'end', 'sortable': True},
                                {'name': 'text', 'label': '内容', 'field': 'text', 'align': 'left'}
                            ],
                            rows=[], row_key='id', selection='single',
                            on_select=lambda e: asyncio.create_task(edit_sub_dialog(next(s for s in state.subtitles if s.id == e.selection[0]['id']))) if e.selection else None
                        ).classes('w-full h-full').props('dark')

@ui.page('/settings')
def settings_page(restart_func):
    ui.dark_mode().enable()
    with ui.column().classes('w-full max-w-2xl mx-auto p-8 gap-6'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('应用设置').classes('text-3xl font-bold')
            ui.button('返回主页', on_click=lambda: ui.navigate.to('/'), icon='home')
        ui.markdown("""
            修改配置后，请**保存**并**重启应用**以使所有更改生效。
            - **Whisper 模型**: 推荐 `large-v3` 以获得最佳效果。
            - **Hugging Face Token**: 必填项，用于从 Hugging Face Hub 下载模型。
        """)
        current_config = get_config()
        with ui.card().props('dark').classes('w-full p-6 gap-4'):
            model_select = ui.select(
                options=['tiny', 'base', 'small', 'medium', 'large-v1', 'large-v2', 'large-v3'],
                label='Whisper 模型',
                value=current_config.get('model_name', 'large-v3')
            ).classes('w-full').props('dark outlined')
            hf_token_input = ui.input(
                label='Hugging Face Token',
                password=True, password_toggle_button=True,
                value=current_config.get('hf_token', '')
            ).classes('w-full').props('dark outlined')
            hf_cache_input = ui.input(
                label='Hugging Face 缓存目录 (可选)',
                placeholder='例如: D:/hf_cache 或 /home/user/hf_cache',
                value=current_config.get('hf_cache_dir', '')
            ).classes('w-full').props('dark outlined')
        def handle_save():
            new_config = {
                'model_name': model_select.value,
                'hf_token': hf_token_input.value,
                'hf_cache_dir': hf_cache_input.value.strip() or None,
            }
            save_config(new_config)
            ui.notify('配置已保存！请重启应用以应用更改。', type='positive', duration=5000)
            restart_func()
        with ui.row().classes('w-full justify-end mt-4'):
            ui.button('保存并提示重启', on_click=handle_save, icon='save', color='primary')