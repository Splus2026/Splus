CLIP = {'text': ''}
FAIL = {'copy': False}
def copy(text):
    if FAIL['copy']:
        raise RuntimeError("буфер обмена недоступен")
    CLIP['text'] = text
    import keyboard
    keyboard.LOG.append(('copy', text))
def paste(): return CLIP['text']
