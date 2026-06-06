import re
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

class PythonHighlighter(QSyntaxHighlighter):
    """Python syntax highlighter using VS Code Dark style colors for both Dark and Light modes."""

    def __init__(self, document, editor=None):
        super().__init__(document)
        self.editor = editor
        self._init_formats()

    def _init_formats(self):
        self.formats = {}
        
        # 1. Keywords - Blue (#569CD6)
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569CD6"))
        keyword_format.setFontWeight(QFont.Bold)
        self.formats["keyword"] = keyword_format
        
        # 2. Functions / Methods - Teal (#4EC9B0)
        func_format = QTextCharFormat()
        func_format.setForeground(QColor("#4EC9B0"))
        func_format.setFontWeight(QFont.Bold)
        self.formats["func"] = func_format
        
        # 3. self - Purple Italic (#A074C4)
        self_format = QTextCharFormat()
        self_format.setForeground(QColor("#A074C4"))
        self_format.setFontItalic(True)
        self.formats["self"] = self_format
        
        # 4. Strings - Orange-Brown (#D69D85)
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#D69D85"))
        self.formats["string"] = string_format
        
        # 5. Comments - Green (#57A64A)
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#57A64A"))
        self.formats["comment"] = comment_format

        # Python 關鍵字集合
        self.keywords = {
            "and", "as", "assert", "break", "class", "continue", "def",
            "del", "elif", "else", "except", "False", "finally", "for",
            "from", "global", "if", "import", "in", "is", "lambda", "None",
            "nonlocal", "not", "or", "pass", "raise", "return", "True",
            "try", "while", "with", "yield"
        }

    def highlightBlock(self, text):
        N = len(text)
        i = 0
        state = self.previousBlockState()
        if state < 0:
            state = 0  # 0: NORMAL, 1: IN_TRIPLE_DOUBLE, 2: IN_TRIPLE_SINGLE
            
        start_idx = 0
        
        while i < N:
            if state == 1:  # IN_TRIPLE_DOUBLE
                if text[i:i+3] == '"""':
                    self.setFormat(start_idx, i + 3 - start_idx, self.formats["string"])
                    i += 3
                    state = 0
                else:
                    i += 1
            elif state == 2:  # IN_TRIPLE_SINGLE
                if text[i:i+3] == "'''":
                    self.setFormat(start_idx, i + 3 - start_idx, self.formats["string"])
                    i += 3
                    state = 0
                else:
                    i += 1
            else:  # NORMAL (state == 0)
                # 1. 註解優先判定
                if text[i] == '#':
                    self.setFormat(i, N - i, self.formats["comment"])
                    break
                    
                # 2. 多行字串開始判定
                elif text[i:i+3] == '"""':
                    start_idx = i
                    state = 1
                    i += 3
                elif text[i:i+3] == "'''":
                    start_idx = i
                    state = 2
                    i += 3
                    
                # 3. 單行字串判定（支持轉義字元）
                elif text[i] == '"' or text[i] == "'":
                    quote = text[i]
                    start_str = i
                    i += 1
                    while i < N:
                        if text[i] == '\\':
                            i += 2  # 跳過轉義字元及其後面的字元
                        elif text[i] == quote:
                            i += 1
                            break
                        else:
                            i += 1
                    self.setFormat(start_str, min(i, N) - start_str, self.formats["string"])
                    
                # 4. 識別字判定（self, 關鍵字, 函數調用）
                elif text[i].isalpha() or text[i] == '_':
                    start_word = i
                    i += 1
                    while i < N and (text[i].isalnum() or text[i] == '_'):
                        i += 1
                    word = text[start_word:i]
                    
                    if word == 'self':
                        self.setFormat(start_word, i - start_word, self.formats["self"])
                    elif word in self.keywords:
                        self.setFormat(start_word, i - start_word, self.formats["keyword"])
                    else:
                        # 檢查是否為函數調用，即後方緊跟著 '('
                        peek = i
                        while peek < N and text[peek].isspace():
                            peek += 1
                        if peek < N and text[peek] == '(':
                            self.setFormat(start_word, i - start_word, self.formats["func"])
                else:
                    i += 1
                    
        # 若該行結束仍處於多行字串狀態，將剩餘部分標記為字串
        if state != 0:
            self.setFormat(start_idx, N - start_idx, self.formats["string"])
            
        self.setCurrentBlockState(state)
