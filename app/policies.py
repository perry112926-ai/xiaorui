"""Versioned language policies; executable business rules live in adapters."""
from pathlib import Path
_ROOT=Path(__file__).with_name('policies')
def load_policy(name):
    if name not in {'general','chat','mcd','weather'}:
        raise ValueError('Unknown policy')
    return (_ROOT/(name+'.txt')).read_text(encoding='utf-8').strip()
GENERAL_POLICY=load_policy('general')
CHAT_POLICY=load_policy('chat')
MCD_POLICY=load_policy('mcd')
WEATHER_POLICY=load_policy('weather')
