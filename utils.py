# utils.py

import pysrt
from dataclasses import dataclass, field
from pathlib import Path

# AppState 可以保持原样
@dataclass
class AppState:
    video_path: Path = None
    subtitles: list = field(default_factory=list)
    selected_sub: 'Sub' = None

# 定义一个 Sub 类来更好地组织数据
@dataclass
class Sub:
    id: int
    start: pysrt.SubRipTime
    end: pysrt.SubRipTime
    speaker: str
    text: str
    pysrt_item: pysrt.SubRipItem # 保留对原始 pysrt 对象的引用，方便编辑和保存

def load_srt_to_subs(srt_path: str) -> list[Sub]:
    """
    加载 SRT 文件并解析出说话人和文本。
    格式假定为 "SPEAKER_ID: Text content"。
    """
    subs = []
    try:
        srt_file = pysrt.open(srt_path, encoding='utf-8')
        for i, item in enumerate(srt_file):
            full_text = item.text.strip()
            speaker = '未知'
            text_content = full_text
            
            # 尝试按冒号分割说话人和内容
            if ': ' in full_text:
                parts = full_text.split(': ', 1)
                # 检查第一部分是否像一个说话人标签 (例如 SPEAKER_00, 不含空格)
                if len(parts) == 2 and not ' ' in parts[0]:
                    speaker = parts[0]
                    text_content = parts[1]

            subs.append(Sub(
                id=i + 1,  # 使用新的连续 ID
                start=item.start,
                end=item.end,
                speaker=speaker,
                text=text_content,
                pysrt_item=item
            ))
        # 重新编号 pysrt 对象，以防原始文件索引不连续
        for i, sub in enumerate(subs):
            sub.pysrt_item.index = i + 1

    except Exception as e:
        print(f"解析 SRT 文件时出错: {e}")
    return subs

@dataclass
class SpeakerBlock:
    """代表一个说话人的连续对话块"""
    speaker: str
    subs: list[Sub] = field(default_factory=list)

    @property
    def start_time(self) -> pysrt.SubRipTime:
        return self.subs[0].start if self.subs else pysrt.SubRipTime()

    @property
    def full_text(self) -> str:
        return " ".join(sub.text for sub in self.subs)

def group_subs_into_blocks(subs: list[Sub]) -> list[SpeakerBlock]:
    """将扁平的字幕列表按说话人连续性分组"""
    if not subs:
        return []

    blocks = []
    current_block = SpeakerBlock(speaker=subs[0].speaker)
    current_block.subs.append(subs[0])

    for i in range(1, len(subs)):
        sub = subs[i]
        if sub.speaker == current_block.speaker:
            current_block.subs.append(sub)
        else:
            blocks.append(current_block)
            current_block = SpeakerBlock(speaker=sub.speaker)
            current_block.subs.append(sub)
    
    blocks.append(current_block) # 不要忘记最后一个块
    return blocks