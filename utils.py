import pysrt
from dataclasses import dataclass
from pathlib import Path
from nicegui import app, ui
from typing import Union


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


@dataclass
class AppState:
    video_path: Union[Path, None] = None
    subtitles: list[Subtitle] = None
    selected_sub: Union[Subtitle, None] = None


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
