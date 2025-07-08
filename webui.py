import tempfile
from pathlib import Path
import pysrt
import asyncio
from nicegui import app, ui
from nicegui.events import UploadEventArguments
# 假设这些是你自己的模块
from get_subtitle import get_subtitle
from utils import load_srt_to_subs, AppState
from config import *

# --- 全局设置 ---
temp_dir = Path('./cache')
temp_dir.mkdir(parents=True, exist_ok=True)
# 映射缓存目录到URL，以便视频可以播放
app.add_media_files('/video', temp_dir)


@ui.page('/')
def main_page():

    state = AppState()

    # --- UI 构建 ---
    with ui.header(elevated=True).classes('justify-between'):
        with ui.row(align_items='center'): # 使用 row 并设置对齐
            ui.label('电影字幕生成器').classes('text-2xl')
            ui.link('设置', '/settings').classes('ml-4 text-white')
        with ui.row():
            video_uploader = ui.upload(on_upload=lambda e: handle_upload(e), auto_upload=True).props(
                'accept="video/*"').style('width:0; height:0; overflow:hidden;')
            upload_button = ui.button(
                '加载视频', on_click=lambda: video_uploader.run_method('pickFiles'), icon='movie')
            generate_button = ui.button(
                '生成字幕', on_click=lambda: generate_subtitles(), icon='subtitles').props('disable')
            save_button = ui.button(
                '保存字幕文件', on_click=lambda: download_srt(), icon='save')

    with ui.grid(columns=2).classes('w-full p-4 gap-4'):
        with ui.column().classes('w-full'):
            with ui.element('div').classes('relative w-full aspect-video bg-black flex items-center justify-center rounded-lg overflow-hidden') as video_container:
                initial_label = ui.label('上传视频以开始').classes('text-2xl text-gray-400')
                video: ui.video = None
                subtitle_label = ui.label('').classes(
                    'absolute text-white font-bold text-2xl text-center w-full transition-all duration-100 hidden'
                ).style(
                    'bottom: 20px; left: 50%; transform: translateX(-50%); text-shadow: 2px 2px 4px black;'
                )
            with ui.card().classes('w-full').bind_visibility_from(state, 'subtitles', backward=lambda subs: bool(subs)):
                ui.label('字幕预览').classes('text-xl font-semibold')
                with ui.row().classes('w-full items-center'):
                    # 上一条字幕 (使用 .bind_text_from() 绑定)
                    with ui.column().classes('w-1/3 text-gray-400 text-sm'):
                        ui.label().bind_text_from(state, 'preview_prev_time')
                        ui.label().classes('line-clamp-2').bind_text_from(state, 'preview_prev_text')
                    
                    # 当前字幕（高亮） (使用 .bind_text_from() 绑定)
                    with ui.card().classes('w-1/3 bg-primary text-white'):
                        ui.label().classes('text-sm font-mono').bind_text_from(state, 'preview_curr_time')
                        ui.label().classes('text-base font-bold').bind_text_from(state, 'preview_curr_text')

                    # 下一条字幕 (使用 .bind_text_from() 绑定)
                    with ui.column().classes('w-1/3 text-gray-400 text-sm'):
                        ui.label().bind_text_from(state, 'preview_next_time')
                        ui.label().classes('line-clamp-2').bind_text_from(state, 'preview_next_text')
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
                
                with ui.row().classes('w-full justify-end'):
                    ui.button('应用更改', on_click=lambda: apply_changes())
                    ui.button('删除', on_click=lambda: delete_sub(), color='negative')

    edit_card.visible = False
    save_button.set_visibility(False)

    async def handle_upload(e: UploadEventArguments):
        nonlocal video, subtitle_label
        upload_button.disable()
        generate_button.props('disable')
        save_button.set_visibility(False)
        table.rows.clear()
        table.update()

        file_path = temp_dir / e.name
        with open(file_path, 'wb') as f:
            f.write(e.content.read())
        state.video_path = file_path

        try:
            video_container.clear()
        except Exception as ex:
            print(f"忽略UI清理异常: {ex}")
        with video_container:
            video = ui.video(f'/video/{state.video_path.name}').classes('w-full')
            # 监听 timeupdate 事件，并将 currentTime 属性传递给处理函数
            # 注意: 这里我们明确指定了 'currentTime'，这样 e.args 就是一个数字了
            # 为了与之前的解释保持一致，我们还是按字典处理，这样更具通用性
            video.on('timeupdate', handle_time_update, throttle=0.2)
            subtitle_label = ui.label('').classes(
                'absolute text-white font-bold text-2xl text-center w-full transition-all duration-100 hidden'
            ).style(
                'bottom: 20px; left: 50%; transform: translateX(-50%); text-shadow: 2px 2px 4px black;'
            )
        
        ui.notify(f"视频 '{e.name}' 上传成功！", type='positive')
        
        upload_button.enable()
        generate_button.props(remove='disable')

    async def generate_subtitles():
        if not state.video_path:
            ui.notify("请先上传一个视频。", type='warning')
            return

        upload_button.disable()
        generate_button.props('disable')
        
        with video_container:
            spinner = ui.spinner(size='lg', color='white').classes('absolute')

        progress_notification = ui.notification(
            '准备开始生成字幕...', position='bottom-right', close_button='OK', timeout=None
        )

        srt_path = None
        try:
            loop = asyncio.get_running_loop()
            srt_path = await loop.run_in_executor(
                None, get_subtitle, str(state.video_path), progress_notification
            )
            
            if srt_path and srt_path.exists():
                state.subtitles = load_srt_to_subs(srt_path)
                table.rows = [{'id': s.id, 'start': str(s.start), 'end': str(s.end), 'text': s.text} for s in state.subtitles]
                table.update()
                save_button.set_visibility(True)
                ui.notify('字幕生成完毕!', type='positive')
            else:
                ui.notify('字幕生成失败，请查看控制台日志。', type='negative')
                
        except Exception as ex:
            ui.notify(f"处理时发生意外错误: {ex}", type='negative')
            
        finally:
            spinner.delete()
            upload_button.enable()
            if not (srt_path and srt_path.exists()):
                generate_button.props(remove='disable')

    def handle_select(selection: list):
        if not selection:
            state.selected_sub = None
            edit_card.visible = False
            return
        row = selection[0]
        sub = next((s for s in state.subtitles if s.id == row['id']), None)
        if sub:
            state.selected_sub = sub
            edit_card.visible = True
            start_input.value = str(sub.pysrt_item.start)
            end_input.value = str(sub.pysrt_item.end)
            text_input.value = sub.text
            if video:
                video.seek(sub.pysrt_item.start.ordinal / 1000)
                video.play()

    def apply_changes():
        sub = state.selected_sub
        if not sub:
            return
        try:
            sub.pysrt_item.start.from_string(start_input.value)
            sub.pysrt_item.end.from_string(end_input.value)
            sub.pysrt_item.text = text_input.value
            for row in table.rows:
                if row['id'] == sub.id:
                    row['start'] = str(sub.start)
                    row['end'] = str(sub.end)
                    row['text'] = sub.text
                    break
            table.update()
            ui.notify('更改已应用！', type='positive')
        except Exception as e:
            ui.notify(f'时间格式无效: {e}', type='negative')

    async def delete_sub():
        sub_to_delete = state.selected_sub
        if not sub_to_delete:
            return

        with ui.dialog() as dialog, ui.card():
            ui.label(f'确定要删除第 {sub_to_delete.id} 行字幕吗？')
            ui.label(f'内容: "{sub_to_delete.text}"')
            with ui.row().classes('w-full justify-end'):
                ui.button('取消', on_click=dialog.close)
                ui.button('确定删除', on_click=lambda: dialog.submit('delete'), color='negative')

        result = await dialog
        
        if result == 'delete':
            state.subtitles.remove(sub_to_delete)
            table.rows = [row for row in table.rows if row['id'] != sub_to_delete.id]
            state.selected_sub = None
            edit_card.visible = False
            table.update()
            ui.notify(f'字幕 {sub_to_delete.id} 已删除。', type='positive')

    # ###############################################
    # ############# 这是修复后的函数 ##############
    # ###############################################
    # ###############################################
# ############# 这是最终的修复方案 ##############
# ###############################################
    def handle_time_update(e):
        """当视频时间更新时，通过修改 state 来更新UI。"""
        # 检查基本条件
        if not state.subtitles or not isinstance(e.args, (int, float)):
            return

        # 获取时间
        current_time_seconds = e.args
        current_time_ms = current_time_seconds * 1000
        
        # 找到当前字幕的索引
        current_sub_index = -1
        for i, sub in enumerate(state.subtitles):
            if sub.pysrt_item.start.ordinal <= current_time_ms < sub.pysrt_item.end.ordinal:
                current_sub_index = i
                break

        # --- 核心改动：不再操作UI，而是修改 state ---

        # 先清空 state 中的预览文本
        state.preview_prev_time = ''
        state.preview_prev_text = ''
        state.preview_curr_time = ''
        state.preview_curr_text = ''
        state.preview_next_time = ''
        state.preview_next_text = ''
        subtitle_label.set_text('')
        subtitle_label.set_visibility(False)

        if current_sub_index != -1:
            # 更新视频上的字幕 (这个可以保留直接操作，因为它比较独立)
            current_sub = state.subtitles[current_sub_index]
            subtitle_label.set_text(current_sub.text)
            subtitle_label.set_visibility(True)

            # 更新 state 来填充字幕预览区
            state.preview_curr_time = f"{current_sub.start} --> {current_sub.end}"
            state.preview_curr_text = current_sub.text

            # 更新上一条字幕的 state
            if current_sub_index > 0:
                prev_sub = state.subtitles[current_sub_index - 1]
                state.preview_prev_time = f"{prev_sub.start} --> {prev_sub.end}"
                state.preview_prev_text = prev_sub.text

            # 更新下一条字幕的 state
            if current_sub_index < len(state.subtitles) - 1:
                next_sub = state.subtitles[current_sub_index + 1]
                state.preview_next_time = f"{next_sub.start} --> {next_sub.end}"
                state.preview_next_text = next_sub.text
    def download_srt():
        if not state.subtitles:
            return
        final_srt = pysrt.SubRipFile([sub.pysrt_item for sub in state.subtitles])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write(str(final_srt))
            temp_srt_path = f.name
        
        ui.download(temp_srt_path, filename=f'{state.video_path.stem}_edited.srt')
        ui.notify('字幕文件即将开始下载。', type='positive')

# ... 你的 settings_page 和其他代码保持不变 ...
# 我把它们从这里省略了，因为它们与错误无关
# 请确保你的文件结构是正确的
@ui.page('/settings')
def settings_page():
    # ... (settings_page 的所有代码) ...
    # 为了完整性，我将它也复制过来
    initial_config = load_config() or {}
    
    config = {
        'model_name': initial_config.get('model_name'),
        'use_deepseek': initial_config.get('use_deepseek', False),
        'deepseek_api_key': initial_config.get('deepseek_api_key', ''),
    }

    validation_state = {'is_valid': is_config_valid(config)}

    def update_validation_state():
        config['model_name'] = model_select.value
        config['use_deepseek'] = deepseek_switch.value
        config['deepseek_api_key'] = api_key_input.value
        validation_state['is_valid'] = is_config_valid(config)
        initialize_button.update()

    async def handle_initialize():
        save_config(config)
        ui.notify('设置已保存！', type='positive')
        ui.navigate.to('/')

    with ui.column().classes('w-full max-w-lg mx-auto p-4 gap-4'):
        ui.label('首次启动设置').classes('text-2xl font-semibold')
        ui.label('请完成以下设置以初始化应用。').classes('text-sm text-gray-500')

        with ui.card().classes('w-full'):
            ui.label('模型设置').classes('text-lg font-medium')
            model_options = ['large-v3', 'medium', 'small', 'base']
            model_select = ui.select(model_options, label='选用模型名称', with_input=True,
                                     value=config['model_name'],
                                     on_change=update_validation_state).classes('w-full')

        with ui.card().classes('w-full'):
            ui.label('AI 辅助').classes('text-lg font-medium')
            deepseek_switch = ui.switch('使用 DeepSeek 辅助润色',
                                        value=config['use_deepseek'],
                                        on_change=update_validation_state)
            
            api_key_input = ui.input('DeepSeek API Key', password=True,
                                     value=config['deepseek_api_key'],
                                     on_change=update_validation_state) \
                                     .classes('w-full').bind_visibility_from(deepseek_switch, 'value')

        initialize_button = ui.button('保存并初始化', on_click=handle_initialize) \
                                .bind_enabled_from(validation_state, 'is_valid')

    update_validation_state()

# 假设 is_config_valid, save_config, load_config 在 config.py 中定义
# def is_config_valid(config): ...
# def save_config(config): ...
# def load_config(): ...