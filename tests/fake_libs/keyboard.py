"""Подмена библиотеки keyboard: хранит хоткеи С ФЛАГОМ suppress; send() только записывает."""
HOTKEYS = {}     # hotkey -> {'callback':..., 'suppress':..., 'handle':...}
SENT = []        # что "отправили" клавишами
LOG = []         # журнал вызовов в порядке времени
FAIL_ADD = set() # клавиши, на которых add_hotkey должен падать

class _Handle:
    def __init__(self, hotkey): self.hotkey = hotkey
    def __repr__(self): return f"<handle {self.hotkey}>"

def add_hotkey(hotkey, callback, args=(), suppress=False, timeout=1, trigger_on_release=False):
    if hotkey in FAIL_ADD:
        raise OSError(f"нет прав на перехват {hotkey}")
    h = _Handle(hotkey)
    HOTKEYS[hotkey] = {'callback': callback, 'suppress': suppress, 'handle': h}
    LOG.append(('add', hotkey, suppress))
    return h

def remove_hotkey(handle):
    for k, v in list(HOTKEYS.items()):
        if v['handle'] is handle:
            del HOTKEYS[k]
            LOG.append(('remove', k))
            return
    raise KeyError(handle)

def unhook_all():
    HOTKEYS.clear()
    LOG.append(('unhook_all',))

def send(keys):
    SENT.append(keys)
    LOG.append(('send', keys))

def reset():
    HOTKEYS.clear(); SENT.clear(); LOG.clear(); FAIL_ADD.clear()
