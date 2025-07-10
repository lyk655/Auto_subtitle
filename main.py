# main.py

import os
import sys
import atexit
import traceback
from pathlib import Path
from typing import Union  # 关键改动 1: 导入 Union
from dotenv import load_dotenv
from nicegui import app, ui, Client

# --- 从我们自己的模块导入 ---
from config import get_config, is_config_valid
from get_subtitle import SubtitleGenerator
from webui import main_page, settings_page

# --- 全局变量 ---
app_config = {}
# 关键改动 2: 使用 Union 替代 |
subtitle_generator: Union[SubtitleGenerator, None] = None

# --- 重启逻辑 ---
RESTART_FILE = Path("restart.flag")
def request_restart():
    RESTART_FILE.touch()
    ui.notify("配置已保存。请关闭此浏览器标签页，然后手动在终端重启服务以应用更改。", duration=None, close_button=True)

def check_for_restart():
    if RESTART_FILE.exists():
        RESTART_FILE.unlink(missing_ok=True)
        print("检测到重启标志，正在关闭服务器...")
        app.shutdown()

# --- 启动流程 ---
def initialize_app():
    global subtitle_generator, app_config
    app_config = get_config()
    
    if is_config_valid(app_config):
        try:
            print("配置有效，正在初始化字幕生成器...")
            subtitle_generator = SubtitleGenerator(config=app_config)
            print("字幕生成器初始化成功。")
        except Exception as e:
            print(f"!!! 致命错误：模型加载失败，应用无法启动 !!!", file=sys.stderr)
            traceback.print_exc()
            subtitle_generator = None
    else:
        print("配置无效或不完整。将仅启动设置页面。")
        subtitle_generator = None

# --- NiceGUI 页面定义 ---
@ui.page('/')
async def index_page(client: Client):
    await client.connected()
    check_for_restart()

    if not subtitle_generator:
        ui.navigate.to('/settings')
        with ui.column().classes('w-full h-screen flex items-center justify-center'):
            ui.label("配置无效，正在跳转到设置页面...").classes("text-2xl m-4")
        return
    
    main_page(subtitle_generator=subtitle_generator, app_config=app_config)

@ui.page('/settings')
async def settings_route(client: Client):
    await client.connected()
    check_for_restart()
    settings_page(restart_func=request_restart)


# --- 主程序入口 ---
if __name__ in {"__main__", "__mp_main__"}:
    load_dotenv()
    STORAGE_SECRET = os.getenv("STORAGE_SECRET")
    if not STORAGE_SECRET:
        print("警告: 环境变量 'STORAGE_SECRET' 未设置。")
        import secrets
        STORAGE_SECRET = secrets.token_hex(16)

    Path('./cache').mkdir(parents=True, exist_ok=True)
    Path('./demucs_output').mkdir(parents=True, exist_ok=True)
    app.add_media_files('/video', './cache')
    
    initialize_app()
    
    atexit.register(lambda: RESTART_FILE.unlink(missing_ok=True))
    
    ui.run(
        title='字幕编辑器',
        port=8082,
        storage_secret=STORAGE_SECRET,
        reload=False
    )