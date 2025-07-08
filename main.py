from pathlib import Path
from nicegui import app, ui
import tempfile
from webui import main_page, settings_page
from config import load_config, is_config_valid

# 1. 移除 @app.on_startup 函数，因为我们不能在这里使用 app.storage.user
# @app.on_startup
# def check_configuration():
#     ...

# 2. 修改 index_page 来处理所有逻辑
@ui.page('/')
def index_page():
    
    config = load_config()
    if not is_config_valid(config):
        # 如果配置无效，直接重定向到设置页面
        ui.navigate.to('/settings')
        # 显示一条消息，以防重定向失败
        ui.label("配置无效，正在跳转到设置页面...").classes("text-2xl m-4")
        return 
    
    main_page()

settings_page()

if __name__ in {"__main__", "__mp_main__"}:
    cache_dir = Path('./cache')
    cache_dir.mkdir(parents=True, exist_ok=True)
    app.add_media_files('/video', cache_dir)
    
    # 3. 添加 storage_secret 来修复第二个错误
    ui.run(
        title='字幕编辑器', 
        uvicorn_reload_dirs=str(Path(__file__).parent), 
        port=8082,
        storage_secret='YOUR_OWN_SECRET_KEY_HERE_12345' # 替换成你自己的密钥
    )