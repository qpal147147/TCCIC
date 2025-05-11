"""config utils"""
import yaml
import re

from pathlib import Path

def get_config(config_path):
    with open(config_path, 'r') as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
    return config

def get_bank_config(config_path, bank_code):
    config = get_config(config_path)
    
    for bank_config in config['banks']:
        if bank_config['bank_code'] == bank_code:
            return bank_config
    return None

def get_model_config(config_path, platform):
    return get_config(config_path)[platform]

def get_llm_config(config_path, platform):
    config = get_config(config_path)[platform]
    if not config:
        return None
    
    return config["llm"]

def get_embedding_config(config_path, platform):
    config = get_config(config_path)[platform]
    if not config:
        return None
    
    return config["embedding"]