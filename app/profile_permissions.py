"""Supported explicit write requests, checked by the host before model tools."""
import re


def profile_write_allowed(text,action):
    verb=r'(?:记住|记下|保存(?:这个|我的|这条|偏好)|remember|save)' if action=='set' else r'(?:忘记|删除|移除|forget|delete)'
    if re.search(r'(?:不要|别|不用|不必|不想|无需|不能|do not|don\x27t)\s*(?:再|帮我)?\s*'+verb,text,re.I):
        return False
    return bool(re.search(r'(?:^|[，。！？,!?\s]|请|帮我)'+verb,text,re.I))
