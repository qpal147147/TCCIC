"""config utils"""
import yaml
import re

from pathlib import Path

def get_config(config_path):
    with open(config_path, 'r') as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
    return config

def get_card_config(bank_config, url):
    for card in bank_config['credit_cards']:
        url_pattern = card['url_pattern']
        if url_pattern and re.match(url_pattern, url):
            return card
    return None