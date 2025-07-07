import json
from pathlib import Path
from typing import Optional

CONFIG_FILE = Path('config.json')

def load_config() -> Optional[dict]:
    """加载配置文件。如果文件不存在或为空，返回 None。"""
    if not CONFIG_FILE.exists() or CONFIG_FILE.stat().st_size == 0:
        return None
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None

def save_config(config: dict):
    """将配置字典保存到文件。"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

def is_config_valid(config: Optional[dict]) -> bool:
    """检查配置是否有效。"""
    if not config:
        return False
    # 规则 1: 必须选择一个模型
    model_ok = 'model_name' in config and config['model_name'] is not None
    # 规则 2: 如果启用了 DeepSeek，API Key 不能为空
    deepseek_ok = (not config.get('use_deepseek', False) or 
                   (config.get('use_deepseek', False) and config.get('deepseek_api_key')))
    return model_ok and deepseek_ok