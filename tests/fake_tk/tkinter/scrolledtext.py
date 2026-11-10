from tkinter import Widget
class ScrolledText(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.content = ''
        self.tagged = []
    def insert(self, index, text, tag=None):
        self.content += text
        self.tagged.append((text, tag))
    def delete(self, a, b=None):
        self.content = ''
        self.tagged = []
    def get(self, a, b=None): return self.content
