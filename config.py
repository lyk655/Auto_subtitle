# config.py

import json
from pathlib import Path

CONFIG_FILE = Path('config.json')

def get_config() -> dict:
    """
    加载配置文件。如果文件不存在，返回一个包含默认值的字典。
    """
    if not CONFIG_FILE.exists() or CONFIG_FILE.stat().st_size == 0:
        # 提供一个默认/空的配置结构
        return {
            'model_name': 'large-v3',
            'use_deepseek': False,
            'deepseek_api_key': None,
            'hf_token': None,
            'hf_cache_dir': None, # 新增：允许用户自定义缓存目录
        }
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # 如果文件损坏，也返回默认值
            return get_config()

def save_config(config: dict):
    """将配置字典保存到文件。"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def is_config_valid(config: dict) -> bool:
    """
    检查加载的配置是否足以启动应用的核心功能。
    """
    if not config:
        return False
    
    # 规则 1: 必须选择一个模型
    model_ok = 'model_name' in config and config.get('model_name')
    
    # 规则 2: 如果启用了 DeepSeek，API Key 不能为空
    deepseek_ok = (not config.get('use_deepseek', False) or 
                   (config.get('use_deepseek', False) and config.get('deepseek_api_key')))
                   
    # 规则 3: Hugging Face Token 必须提供 (pyannote 需要)
    hf_token_ok = 'hf_token' in config and config.get('hf_token')

    return model_ok and deepseek_ok and hf_token_ok