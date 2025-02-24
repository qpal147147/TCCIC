"""config utils"""
import yaml
import re

from pathlib import Path

def get_config(config_path):
    with open(config_path, 'r') as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
    return config

def get_bank_config(config, bank_code):
    for bank_config in config['banks']:
        if bank_config['bank_code'] == bank_code:
            return bank_config
    return None

def get_card_config(bank_config, url):
    for card in bank_config['credit_cards']:
        url_pattern = card['url_pattern']
        if url_pattern and re.match(url_pattern, url):
            return card
    return None

def get_bank_and_card_name(config_path, bank_code, url):
    bank_config = get_bank_config(get_config(config_path), bank_code)
    card_config = get_card_config(bank_config, url)
    if not card_config:
        return None, None
    
    return bank_config['bank_name'], card_config['card_name']