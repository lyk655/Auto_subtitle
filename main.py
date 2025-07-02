from pathlib import Path
from nicegui import app, ui
import tempfile
from webui import main_page


if __name__ in {"__main__", "__mp_main__"}:
    app.add_static_files('/video', tempfile.gettempdir())
    # You might want to expose the output directory as well for debugging
    app.add_static_files('/output', 'demucs_output')
    ui.run(title='字幕编辑器', uvicorn_reload_dirs=str(
        Path(__file__).parent), port=8082)
