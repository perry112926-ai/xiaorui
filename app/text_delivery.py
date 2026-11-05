"""Immediate conversational receipts, without claiming a query has succeeded."""
import re


def lightweight_chat(text):
    """Only explicit casual conversation; ambiguous task continuations keep tools."""
    if re.search(r'查|搜索|实时|最新|天气|路线|附近|店|吃|餐|咖啡|外卖|打车|叫车|出行|机票|订单|下单|支付|付款|取消|确认|选择|第[一二三四五六七八九十\d]|地址|电话|联系|资料|保存|记住|忘记|提醒|定位|地图|药|病|血压', text):
        return False
    return bool(re.search(r'聊|无聊|心情|周末|放松|休息|故事|笑话|鼓励|开心|难过|寂寞|孤单|陪我', text))


def quick_answer(text):
    normalized=re.sub(r'[\s，。！？,.!?、]','',text)
    if re.fullmatch(r'喂{1,3}|你好|您好|小瑞|在吗|你在吗',normalized):
        return '我在，您说。'
    if normalized in {'谢谢','谢谢你','谢谢您','好的谢谢'}:
        return '不客气。'
    if normalized in {'等一下','我想想','让我想想','稍等'}:
        return '好，您慢慢想，我在。'
    return None


def acknowledgement(text):
    if quick_answer(text):
        return ''
    if re.search(r'确认|取消|下单|付款|支付',text):
        return '收到，我先核对一下。'
    if re.search(r'查|天气|路线|附近|找|打车|叫车|点餐|外卖',text):
        return '好，我帮您看看。'
    return '收到，我看看。'
