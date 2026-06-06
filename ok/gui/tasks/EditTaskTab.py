import os
import re

from PySide6.QtCore import QFileSystemWatcher, QUrl, QPointF
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QFont, QColor, QPainter, QDesktopServices, QPen, QTextCursor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QMessageBox, QTreeWidgetItem, QFileDialog, QPlainTextEdit
from qfluentwidgets import MessageBox, PlainTextEdit, PushButton, FluentIcon, PrimaryPushButton, SearchLineEdit, \
    BodyLabel, ComboBox, RoundMenu, Action, TreeWidget, TransparentDropDownPushButton, CheckBox, isDarkTheme

from ok import og
from ok.gui.tasks.PythonHighlighter import PythonHighlighter
from ok.gui.tasks.TemplateFactory import TemplateFactory, get_templates, filter_templates
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.code_editor.line_number_area_paint_event(event)

    def mousePressEvent(self, event):
        self.code_editor.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.code_editor.mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.code_editor.leaveEvent(event)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.error_line_number = -1
        self.adjusting_scroll = False
        self._occurrence_selections = []
        self._parenthesis_positions = (-1, -1)
        self.viewport().setMouseTracking(True)
        self._sticky_hover_idx = -1
        
        # Adjust cursor width to make it slightly bolder and more readable (like modern IDEs)
        self.setCursorWidth(2)
        
        # Configure QPalette dynamically for light/dark theme adaptation
        self._update_palette_for_theme()
        
        # Apply standard styles matching Fluent design, but strictly WITHOUT hardcoded color backgrounds
        # so that it inherits the correct background and foreground colors from theme palette natively.
        self.setStyleSheet("""
            QPlainTextEdit {
                border: 1px solid rgba(0, 0, 0, 13);
                border-bottom: 1px solid rgba(0, 0, 0, 100);
                border-radius: 5px;
                padding: 2px 3px 2px 8px;
            }
            QPlainTextEdit:focus {
                border-bottom: 1px solid #009FAA;
            }
        """)
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.verticalScrollBar().rangeChanged.connect(self.adjust_scroll_range)
        
        self._effective_indents = []
        self._update_effective_indents()
        self.textChanged.connect(self._update_effective_indents)
        
        self.update_line_number_area_width(0)

    def _update_effective_indents(self):
        """Precompute the effective indentation for all blocks in the document."""
        block_count = self.blockCount()
        if block_count <= 0:
            self._effective_indents = []
            return
            
        indents = [0] * block_count
        is_empty = [True] * block_count
        
        block = self.document().firstBlock()
        while block.isValid():
            idx = block.blockNumber()
            if idx >= block_count:
                break
            text = block.text()
            if text.strip():
                is_empty[idx] = False
                leading = 0
                for ch in text:
                    if ch == ' ':
                        leading += 1
                    elif ch == '\t':
                        leading += 4
                    else:
                        break
                indents[idx] = leading
            block = block.next()
            
        # Forward pass to fill prev_indent
        prev_indent = 0
        prev_indents = [0] * block_count
        for idx in range(block_count):
            if not is_empty[idx]:
                prev_indent = indents[idx]
            prev_indents[idx] = prev_indent
            
        # Backward pass to fill next_indent
        next_indent = 0
        next_indents = [0] * block_count
        for idx in range(block_count - 1, -1, -1):
            if not is_empty[idx]:
                next_indent = indents[idx]
            next_indents[idx] = next_indent
            
        # Combine
        self._effective_indents = [0] * block_count
        for idx in range(block_count):
            if not is_empty[idx]:
                self._effective_indents[idx] = indents[idx]
            else:
                self._effective_indents[idx] = min(prev_indents[idx], next_indents[idx])

    def _update_palette_for_theme(self):
        """Update palette selection colors and stylesheet background based on theme."""
        if getattr(self, '_updating_theme_palette', False):
            return
        self._updating_theme_palette = True
        try:
            from PySide6.QtGui import QPalette, QBrush
            is_dark = isDarkTheme()
            pal = self.palette()
            if is_dark:
                pal.setColor(QPalette.Highlight, QColor(60, 120, 180, 100)) # Semi-transparent blue for dark mode
            else:
                pal.setColor(QPalette.Highlight, QColor(0, 120, 215, 60))    # Faint theme blue for light mode
            pal.setBrush(QPalette.HighlightedText, QBrush())                 # Keep original syntax colors
            self.setPalette(pal)
            
            # Apply adaptive QSS for backgrounds using specific CodeEditor class selector
            if is_dark:
                self.setStyleSheet("""
                    CodeEditor {
                        color: #DCDCDC;
                        background-color: #1E1E1E;
                        border: 1px solid rgba(255, 255, 255, 15);
                        border-bottom: 1px solid rgba(255, 255, 255, 100);
                        border-radius: 5px;
                        padding: 2px 3px 2px 8px;
                    }
                    CodeEditor:focus {
                        border-bottom: 1px solid #009FAA;
                    }
                """)
            else:
                self.setStyleSheet("""
                    CodeEditor {
                        color: #000000;
                        background-color: #FFFFFF;
                        border: 1px solid rgba(0, 0, 0, 15);
                        border-bottom: 1px solid rgba(0, 0, 0, 100);
                        border-radius: 5px;
                        padding: 2px 3px 2px 8px;
                    }
                    CodeEditor:focus {
                        border-bottom: 1px solid #009FAA;
                    }
                """)
                
            if hasattr(self, 'highlighter') and self.highlighter:
                self.highlighter.rehighlight()
        finally:
            self._updating_theme_palette = False

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.PaletteChange, QEvent.StyleChange):
            self._update_palette_for_theme()

    def _on_cursor_position_changed(self):
        """Handle cursor position change: update line number highlight, word occurrences, and parenthesis matching."""
        self.line_number_area.update()
        self._highlight_same_words()
        self._highlight_parentheses()
        self.viewport().update()

    def _highlight_same_words(self):
        """Highlight all occurrences of the word under cursor, similar to IDE behavior."""
        from PySide6.QtGui import QTextCursor
        
        cursor = self.textCursor()
        # Don't highlight when there is a selection
        if cursor.hasSelection():
            self._occurrence_selections = []
            self.setExtraSelections(self._get_merged_extra_selections())
            return
        
        # Select the word under cursor
        cursor.select(QTextCursor.WordUnderCursor)
        word = cursor.selectedText().strip()
        
        # Only highlight identifiers (letters, digits, underscores), min 2 chars
        if not word or len(word) < 2 or not all(c.isalnum() or c == '_' for c in word):
            self._occurrence_selections = []
            self.setExtraSelections(self._get_merged_extra_selections())
            return
        
        selections = []
        # Adaptive highlight background: soft gray for dark mode, warm light gray for light mode
        is_dark = isDarkTheme()
        highlight_color = QColor(80, 80, 80, 120) if is_dark else QColor(220, 220, 220, 140)
        
        doc = self.document()
        search_cursor = QTextCursor(doc)
        
        from PySide6.QtGui import QTextDocument
        while True:
            # Use FindWholeWords to accurately highlight full word matches and handle self.xxx boundary contexts
            search_cursor = doc.find(word, search_cursor, QTextDocument.FindWholeWords)
            if search_cursor.isNull():
                break
            if search_cursor.selectionStart() == search_cursor.selectionEnd():
                break
                
            from PySide6.QtWidgets import QTextEdit
            sel = QTextEdit.ExtraSelection()
            sel.cursor = search_cursor
            sel.format.setBackground(highlight_color)
            selections.append(sel)
        
        self._occurrence_selections = selections
        self.setExtraSelections(self._get_merged_extra_selections())

    def _highlight_parentheses(self):
        """Highlight matching parentheses/brackets near or enclosing the cursor, matching IDE behavior."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            self._parenthesis_positions = (-1, -1)
            return
            
        pos = cursor.position()
        doc = self.document()
        text = doc.toPlainText()
        n = len(text)
        
        bracket_chars = "()[]{}"
        target_pos = -1
        bracket_char = ''
        
        # 1. First prioritize brackets immediately adjacent to the cursor (left then right)
        if pos > 0 and text[pos - 1] in bracket_chars:
            target_pos = pos - 1
            bracket_char = text[pos - 1]
        elif pos < n and text[pos] in bracket_chars:
            target_pos = pos
            bracket_char = text[pos]
            
        match_pos = -1
        if target_pos != -1:
            match_pos = self._find_matching_bracket_pos(text, target_pos, bracket_char)
            
        # 2. If cursor is not next to a bracket, scan left to find the nearest enclosing bracket pair
        if match_pos == -1:
            stack = []
            left_pos = -1
            left_char = ''
            
            for i in range(pos - 1, -1, -1):
                c = text[i]
                if c in ")]}":
                    if c == ')': stack.append('(')
                    elif c == ']': stack.append('[')
                    elif c == '}': stack.append('{')
                elif c in "([{":
                    if stack and stack[-1] == c:
                        stack.pop()
                    else:
                        left_pos = i
                        left_char = c
                        break
            
            if left_pos != -1:
                m_pos = self._find_matching_bracket_pos(text, left_pos, left_char)
                if m_pos != -1 and m_pos >= pos:
                    target_pos = left_pos
                    match_pos = m_pos
                    
        if target_pos == -1 or match_pos == -1:
            self._parenthesis_positions = (-1, -1)
        else:
            self._parenthesis_positions = (target_pos, match_pos)

    def _find_matching_bracket_pos(self, text, pos, char):
        """Walk text to find matching parenthesis/bracket index supporting nested structures."""
        bracket_pairs = {
            '(': (')', 1),
            '[': (']', 1),
            '{': ('}', 1),
            ')': ('(', -1),
            ']': ('[', -1),
            '}': ('{', -1)
        }
        
        partner, direction = bracket_pairs[char]
        depth = 0
        n = len(text)
        
        i = pos + direction
        while 0 <= i < n:
            c = text[i]
            if c == char:
                depth += 1
            elif c == partner:
                if depth == 0:
                    return i
                else:
                    depth -= 1
            i += direction
            
        return -1

    def setExternalExtraSelections(self, selections):
        """Set extra selections from external callers (e.g. diff highlights).
        These are merged with internal occurrence highlights."""
        self._external_selections = list(selections)
        self.setExtraSelections(self._get_merged_extra_selections())

    def _get_merged_extra_selections(self):
        """Merge occurrence highlight selections with any external extra selections."""
        external = getattr(self, '_external_selections', [])
        return list(external) + list(self._occurrence_selections)

    def _get_current_sticky_blocks(self):
        """Helper to get parent classes and functions that should stick to the top."""
        first_block = self.firstVisibleBlock()
        first_block_num = first_block.blockNumber()
        
        if first_block_num <= 0 or first_block == self.document().lastBlock():
            return []
            
        # Determine search start block depending on whether the first block is partially scrolled out
        first_block_top = self.blockBoundingGeometry(first_block).translated(self.contentOffset()).top()
        start_block = first_block if first_block_top < 0 else first_block.previous()
        
        if not start_block.isValid():
            return []
            
        sticky_blocks = []
        text = start_block.text()
        start_indent = 0
        for ch in text:
            if ch == ' ': start_indent += 1
            elif ch == '\t': start_indent += 4
            else: break
            
        current_indent = start_indent + 1
        
        curr_b = start_block
        while curr_b.isValid():
            b_text = curr_b.text()
            if not b_text.strip():
                curr_b = curr_b.previous()
                continue
                
            b_indent = 0
            for ch in b_text:
                if ch == ' ': b_indent += 1
                elif ch == '\t': b_indent += 4
                else: break
                
            if b_indent < current_indent:
                stripped = b_text.strip()
                if stripped.startswith("class ") or stripped.startswith("def "):
                    sticky_blocks.insert(0, curr_b)
                    current_indent = b_indent
                    if current_indent == 0:
                        break
            curr_b = curr_b.previous()
            
        return sticky_blocks

    def line_number_area_width(self):
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num /= 10
            digits += 1
        space = 20 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def update_line_number_area_width(self, new_block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def adjust_scroll_range(self, min_val, max_val):
        if self.adjusting_scroll:
            return
        if max_val <= 0:
            bar = self.verticalScrollBar()
            if bar.maximum() != 0:
                self.adjusting_scroll = True
                try:
                    bar.setMaximum(0)
                finally:
                    self.adjusting_scroll = False
            return
            
        self.adjusting_scroll = True
        try:
            line_height = self.fontMetrics().height()
            if line_height > 0:
                viewport_height = self.viewport().height()
                bar = self.verticalScrollBar()
                
                # Calculate actual total visual lines by traversing and summing block layouts
                total_visual_lines = 0
                block = self.document().firstBlock()
                while block.isValid():
                    total_visual_lines += max(1, block.layout().lineCount())
                    block = block.next()
                
                from PySide6.QtWidgets import QPlainTextEdit
                if self.lineWrapMode() == QPlainTextEdit.NoWrap:
                    # In NoWrap, vertical scroll index corresponds 1-to-1 with block number.
                    # Setting maximum to min(max_val + visible_lines + 1, blockCount() - 1) prevents invalid block index queries.
                    # We use ceiling division buffer via + 1 to overcome rounding issues.
                    visible_lines_ceil = (viewport_height + line_height - 1) // line_height
                    new_max = min(max_val + visible_lines_ceil + 1, self.blockCount() - 1)
                else:
                    # In WordWrap, scroll index is visual line index.
                    # We cap at total_visual_lines - 1 to prevent out-of-bounds scrolling (value > visual lines)
                    visible_lines = viewport_height // line_height
                    new_max = min(max_val + visible_lines - 1, total_visual_lines - 1)
                    
                bar.setMaximum(new_max)
        finally:
            self.adjusting_scroll = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def wheelEvent(self, event):
        """Handle Shift+Wheel for horizontal scrolling, and block Ctrl+Wheel zoom."""
        if event.modifiers() & Qt.ControlModifier:
            # Block Ctrl+Wheel zoom to match upstream unzoomable behavior
            event.accept()
        elif event.modifiers() & Qt.ShiftModifier:
            delta = event.angleDelta().y() or event.angleDelta().x()
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta // 4)
            event.accept()
        else:
            super().wheelEvent(event)

    def toggle_word_wrap(self):
        """Toggle word wrap mode for the editor."""
        from PySide6.QtWidgets import QPlainTextEdit
        if self.lineWrapMode() == QPlainTextEdit.NoWrap:
            self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        else:
            self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def contextMenuEvent(self, event):
        """Override to insert Word Wrap toggle action into standard context menu."""
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        
        from qfluentwidgets import Action
        from PySide6.QtWidgets import QPlainTextEdit
        
        is_wrapped = self.lineWrapMode() == QPlainTextEdit.WidgetWidth
        wrap_action = Action(self.tr("Word Wrap"), self)
        wrap_action.setCheckable(True)
        wrap_action.setChecked(is_wrapped)
        wrap_action.setShortcut("Alt+Z")
        wrap_action.triggered.connect(self.toggle_word_wrap)
        
        menu.addAction(wrap_action)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event):
        """Override mousePressEvent to handle clicking on Sticky Scroll items for definition jumping."""
        sticky_blocks = self._get_current_sticky_blocks()
        if sticky_blocks:
            line_height = self.fontMetrics().height()
            margin = 4
            sticky_line_height = line_height + margin
            total_height = len(sticky_blocks) * sticky_line_height
            
            if event.y() <= total_height:
                idx = event.y() // sticky_line_height
                if 0 <= idx < len(sticky_blocks):
                    block = sticky_blocks[idx]
                    cursor = self.textCursor()
                    cursor.setPosition(block.position())
                    self.setTextCursor(cursor)
                    self.verticalScrollBar().setValue(max(0, block.blockNumber() - 5))
                    self.viewport().update()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Override mouseMoveEvent to update hover index and change cursor shape on Sticky Scroll."""
        sticky_blocks = self._get_current_sticky_blocks()
        if sticky_blocks:
            line_height = self.fontMetrics().height()
            margin = 4
            sticky_line_height = line_height + margin
            total_height = len(sticky_blocks) * sticky_line_height
            
            if event.y() <= total_height:
                self.viewport().setCursor(Qt.PointingHandCursor)
                hover_idx = event.y() // sticky_line_height
                if getattr(self, '_sticky_hover_idx', -1) != hover_idx:
                    self._sticky_hover_idx = hover_idx
                    self.viewport().update()
                super().mouseMoveEvent(event)
                return
                
        if getattr(self, '_sticky_hover_idx', -1) != -1:
            self._sticky_hover_idx = -1
            self.viewport().setCursor(Qt.IBeamCursor)
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        """Reset hover states when mouse leaves the editor."""
        if getattr(self, '_sticky_hover_idx', -1) != -1:
            self._sticky_hover_idx = -1
            self.viewport().setCursor(Qt.IBeamCursor)
            self.viewport().update()
        super().leaveEvent(event)

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor(Qt.transparent))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        font_metrics = self.fontMetrics()
        cursor_line = self.textCursor().blockNumber() + 1
        
        is_dark = isDarkTheme()
        
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                
                if (block_number + 1) == self.error_line_number:
                    painter.setPen(Qt.red)
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)
                elif (block_number + 1) == cursor_line:
                    painter.setPen(QColor(220, 220, 220) if is_dark else QColor(30, 30, 30))
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(Qt.gray)
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)

                painter.drawText(0, int(top), self.line_number_area.width() - 12, int(font_metrics.height()),
                                 Qt.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

        # Draw Sticky Scroll line numbers matching viewport's Sticky Scroll
        sticky_blocks = self._get_current_sticky_blocks()
        if sticky_blocks:
            line_height = self.fontMetrics().height()
            margin = 4
            sticky_line_height = line_height + margin
            total_height = len(sticky_blocks) * sticky_line_height
            
            if is_dark:
                bg_color = QColor(30, 30, 30, 240)
                border_color = QColor(80, 80, 80, 100)
                text_fg = Qt.gray
                hover_bg = QColor(255, 255, 255, 15)
            else:
                bg_color = QColor(243, 243, 243, 245)
                border_color = QColor(200, 200, 200, 180)
                text_fg = QColor(120, 120, 120)
                hover_bg = QColor(0, 0, 0, 12)
                
            # Draw panel background covering rolled-up line numbers underneath
            painter.fillRect(0, 0, self.line_number_area.width(), total_height, bg_color)
            
            # Bottom border line
            painter.setPen(QPen(border_color, 1))
            painter.drawLine(0, total_height, self.line_number_area.width(), total_height)
            
            for idx, b in enumerate(sticky_blocks):
                y_pos = idx * sticky_line_height + margin // 2
                
                # Draw hover effect
                if idx == getattr(self, '_sticky_hover_idx', -1):
                    painter.fillRect(0, idx * sticky_line_height, self.line_number_area.width(), sticky_line_height, hover_bg)
                
                line_num_str = str(b.blockNumber() + 1)
                
                painter.save()
                font = painter.font()
                font.setBold(False)
                painter.setFont(font)
                painter.setPen(text_fg)
                
                # Draw line number matching the Sticky definition block
                painter.drawText(0, int(y_pos), self.line_number_area.width() - 12, int(font_metrics.height()),
                                 Qt.AlignRight, line_num_str)
                painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        # Determine theme lightness for adaptive styling
        from PySide6.QtGui import QPalette
        is_dark = self.palette().color(QPalette.Base).lightness() < 128
        
        if is_dark:
            guide_color = QColor(128, 128, 128, 45)
            active_guide_color = QColor(180, 180, 180, 100)
        else:
            guide_color = QColor(0, 0, 0, 25)
            active_guide_color = QColor(0, 0, 0, 65)
        
        char_width = self.fontMetrics().horizontalAdvance(' ')
        if char_width <= 0:
            painter.end()
            return
        
        # Ensure effective indents cache is valid
        if not hasattr(self, '_effective_indents') or len(self._effective_indents) != self.blockCount():
            self._update_effective_indents()
        
        # Determine cursor line's indentation depth for active guide highlight
        cursor_block = self.textCursor().block()
        cursor_block_number = cursor_block.blockNumber()
        cursor_leading = self._effective_indents[cursor_block_number] if cursor_block_number < len(self._effective_indents) else 0
        
        # The active guide column is the parent guide layer of cursor line's indent level
        # Only highlight if cursor_leading > 0
        active_start_block = -1
        active_end_block = -1
        cursor_guide_col = -1
        
        if cursor_leading > 0 and len(self._effective_indents) > 0:
            cursor_guide_col = max(0, ((cursor_leading - 1) // 4) * 4)
            active_start_block = cursor_block_number
            active_end_block = cursor_block_number
            
            # Walk up to find the start of the block with indent >= cursor_guide_col
            for idx in range(cursor_block_number - 1, -1, -1):
                if idx < len(self._effective_indents):
                    if self._effective_indents[idx] <= cursor_guide_col:
                        break
                    active_start_block = idx
                
            # Walk down to find the end of the block with indent >= cursor_guide_col
            for idx in range(cursor_block_number + 1, len(self._effective_indents)):
                if self._effective_indents[idx] <= cursor_guide_col:
                    break
                active_end_block = idx
            
        # Dictionary to track guides being merged and drawn
        # Format: col -> {'y_start': float, 'y_end': float, 'is_active': bool}
        pending_guides = {}
        viewport_rect = self.viewport().rect()
        
        def draw_guide(col, data):
            x = int(self.contentOffset().x() + col * char_width)
            if x >= 0 and x <= viewport_rect.right():
                if data['is_active']:
                    painter.setPen(active_guide_color)
                else:
                    painter.setPen(guide_color)
                # Draw a single unified line for the merged range
                painter.drawLine(x, int(data['y_start']), x, int(data['y_end']) + 1)

        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        
        while block.isValid() and top <= viewport_rect.bottom():
            if block.isVisible() and bottom >= viewport_rect.top():
                block_num = block.blockNumber()
                leading_spaces = self._effective_indents[block_num] if block_num < len(self._effective_indents) else 0
                is_active_range = (active_start_block <= block_num <= active_end_block)
                
                # Columns that need to be drawn in this block (include 0, exclude leading_spaces itself)
                active_cols = set(range(0, leading_spaces, 4))
                
                # 1. Process active columns in this block
                for col in active_cols:
                    is_active = (is_active_range and col == cursor_guide_col)
                    if col in pending_guides:
                        p_data = pending_guides[col]
                        # Merge if the new segment is contiguous (close enough) and has the same highlight state
                        if p_data['is_active'] == is_active and abs(p_data['y_end'] - top) <= 2.0:
                            p_data['y_end'] = bottom
                        else:
                            # Flush old segment and start new one
                            draw_guide(col, p_data)
                            pending_guides[col] = {'y_start': top, 'y_end': bottom, 'is_active': is_active}
                    else:
                        pending_guides[col] = {'y_start': top, 'y_end': bottom, 'is_active': is_active}
                        
                # 2. Flush and remove any pending columns that are not present in this block
                cols_to_remove = []
                for col, p_data in pending_guides.items():
                    if col not in active_cols:
                        draw_guide(col, p_data)
                        cols_to_remove.append(col)
                for col in cols_to_remove:
                    del pending_guides[col]
                        
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            
        # Flush all remaining pending guides at the end
        for col, p_data in pending_guides.items():
            draw_guide(col, p_data)

        # Draw white thin rectangle border frames around the matching parenthesis pair
        parenthesis_positions = getattr(self, '_parenthesis_positions', (-1, -1))
        if parenthesis_positions != (-1, -1):
            text = self.document().toPlainText()
            n = len(text)
            
            # Use semi-transparent light gray/white pen for dark mode, or blue theme border for light mode
            if is_dark:
                border_pen = QPen(QColor(220, 220, 220, 160), 1)
            else:
                border_pen = QPen(QColor(0, 120, 215, 180), 1)
            painter.setPen(border_pen)
            
            from PySide6.QtCore import Qt
            painter.setBrush(Qt.NoBrush)
            
            pos1, pos2 = parenthesis_positions
            # Sort positions to ensure pos1 < pos2
            if pos1 > pos2:
                pos1, pos2 = pos2, pos1
                
            # If the two brackets are adjacent (e.g. ()), merge them into a single rectangle box
            if pos2 - pos1 == 1 and 0 <= pos1 < n and 0 <= pos2 < n:
                c = QTextCursor(self.document())
                c.setPosition(pos1)
                rect = self.cursorRect(c)
                if rect.bottom() >= 0 and rect.top() <= self.viewport().height():
                    char1 = text[pos1]
                    char2 = text[pos2]
                    w1 = self.fontMetrics().horizontalAdvance(char1)
                    w2 = self.fontMetrics().horizontalAdvance(char2)
                    rect.setWidth(w1 + w2)
                    rect.adjust(0, 1, 0, -1)
                    painter.drawRect(rect)
            else:
                for pos in (pos1, pos2):
                    if 0 <= pos < n:
                        c = QTextCursor(self.document())
                        c.setPosition(pos)
                        rect = self.cursorRect(c)
                        
                        # Only paint if the character is currently visible in the viewport
                        if rect.bottom() >= 0 and rect.top() <= self.viewport().height():
                            char = text[pos]
                            char_width = self.fontMetrics().horizontalAdvance(char)
                            rect.setWidth(char_width)
                            # Slightly adjust rect margins so the outline box frames the character beautifully
                            rect.adjust(0, 1, 0, -1)
                            painter.drawRect(rect)

        # Draw Sticky Scroll top headers representing parent scope context
        sticky_blocks = self._get_current_sticky_blocks()
        if sticky_blocks:
            line_height = self.fontMetrics().height()
            margin = 4
            sticky_line_height = line_height + margin
            total_height = len(sticky_blocks) * sticky_line_height
            
            # Sleek background matching theme lightness
            if is_dark:
                bg_color = QColor(30, 30, 30, 240)
                border_color = QColor(80, 80, 80, 100)
                hover_bg = QColor(255, 255, 255, 15)
            else:
                bg_color = QColor(243, 243, 243, 245)
                border_color = QColor(200, 200, 200, 180)
                hover_bg = QColor(0, 0, 0, 12)
                
            painter.fillRect(0, 0, self.viewport().width(), total_height, bg_color)
            
            # Border under the panel
            painter.setPen(QPen(border_color, 1))
            painter.drawLine(0, total_height, self.viewport().width(), total_height)
            
            for idx, b in enumerate(sticky_blocks):
                y_pos = idx * sticky_line_height + margin // 2
                
                # Highlight hover item with a subtle background light
                if idx == getattr(self, '_sticky_hover_idx', -1):
                    painter.fillRect(0, idx * sticky_line_height, self.viewport().width(), sticky_line_height, hover_bg)
                
                painter.save()
                # Draw the entire block layout with syntax colors directly to share implementation
                b.layout().draw(painter, QPointF(self.contentOffset().x(), y_pos))
                painter.restore()
        
        painter.end()

    def set_error_line(self, line_number):
        self.error_line_number = line_number
        self.line_number_area.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                start_block = self.document().findBlock(cursor.selectionStart()).blockNumber()
                end_block = self.document().findBlock(cursor.selectionEnd()).blockNumber()
                
                cursor.beginEditBlock()
                for i in range(start_block, end_block + 1):
                    block = self.document().findBlockByNumber(i)
                    block_cursor = self.textCursor()
                    block_cursor.setPosition(block.position())
                    block_cursor.insertText("    ")
                cursor.endEditBlock()
                return
            else:
                cursor.insertText("    ")
                return
        elif event.key() == Qt.Key_Backtab:
            from PySide6.QtGui import QTextCursor
            cursor = self.textCursor()
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            start_block = self.document().findBlock(start_pos).blockNumber()
            end_block = self.document().findBlock(end_pos).blockNumber()
            
            cursor.beginEditBlock()
            for i in range(start_block, end_block + 1):
                block = self.document().findBlockByNumber(i)
                block_cursor = self.textCursor()
                block_cursor.setPosition(block.position())
                
                line_text = block.text()
                spaces = 0
                for c in line_text:
                    if c == ' ' and spaces < 4:
                        spaces += 1
                    else:
                        break
                if spaces > 0:
                    block_cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, spaces)
                    block_cursor.removeSelectedText()
            cursor.endEditBlock()
            return
            
        super().keyPressEvent(event)


class EditTaskTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("EditTaskTab")
        self.task = None
        self.python_file = None
        self.all_templates = get_templates()
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.fileChanged.connect(self.on_file_changed)
        self.init_ui()

    def _update_file_watcher(self):
        if self.file_watcher.files():
            self.file_watcher.removePaths(self.file_watcher.files())
        if self.python_file and os.path.exists(self.python_file):
            self.file_watcher.addPath(self.python_file)
            self._last_mtime = os.path.getmtime(self.python_file)

    def on_file_changed(self, path):
        if path == self.python_file and os.path.exists(path):
            try:
                current_mtime = os.path.getmtime(path)
                if hasattr(self, '_last_mtime') and current_mtime == self._last_mtime:
                    return
                self._last_mtime = current_mtime

                with open(path, 'r', encoding='utf-8') as f:
                    new_content = f.read()

                if new_content == self.editor.toPlainText():
                    return

                if getattr(self, 'editor', None) and self.editor.document().isModified():
                    reply = QMessageBox.question(self, self.tr('File Changed Externally'),
                                                 self.tr("The file was modified externally. Do you want to overwrite your unsaved changes?"),
                                                 QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.No:
                        return

                if getattr(self, 'editor', None):
                    cursor = self.editor.textCursor()
                    pos = cursor.position()
                    v_scroll = self.editor.verticalScrollBar().value()
                    
                    self.editor.setPlainText(new_content)
                    self.editor.document().setModified(False)
                    
                    cursor.setPosition(min(pos, len(new_content)))
                    self.editor.setTextCursor(cursor)
                    self.editor.verticalScrollBar().setValue(v_scroll)
                
                # Re-add path in case the editor saved via rename
                self._update_file_watcher()
            except Exception as e:
                logger.error(f"Error handling file change: {e}")

    def load_task(self, task):
        self.task = task
        self.python_file = og.task_manager.task_map.get(task, [None])[0]
        self._load_file_content()

    def _load_file_content(self):
        if self.python_file and os.path.exists(self.python_file):
            self.save_action.setVisible(True)
            self.delete_action.setVisible(True)
            with open(self.python_file, 'r', encoding='utf-8') as f:
                self.editor.setPlainText(f.read())
            self.editor.document().setModified(False)
            self._update_file_watcher()
            # Select correct dropdown index
            for i in range(self.task_dropdown.count()):
                if self.task_dropdown.itemData(i) == self.python_file:
                    self.task_dropdown.blockSignals(True)
                    self.task_dropdown.setCurrentIndex(i)
                    self._current_dropdown_index = i
                    self.task_dropdown.blockSignals(False)
                    break
        else:
            self.save_action.setVisible(False)
            self.delete_action.setVisible(False)
            self.editor.clear()
            self.editor.document().setModified(False)
            self._update_file_watcher()
        self.editor.setFocus()

    def init_ui(self):
        self.layout = QHBoxLayout(self)

        # Left: Template Chooser with search filter
        self.template_panel = QVBoxLayout()
        
        self.search_filter = SearchLineEdit()
        self.search_filter.setPlaceholderText(self.tr("Search templates..."))
        self.search_filter.textChanged.connect(self.on_search_changed)
        self.template_panel.addWidget(self.search_filter)
        
        self.template_list = TreeWidget()
        self.template_list.setBorderVisible(True)
        self.template_list.setBorderRadius(8)
        self.template_list.setHeaderHidden(True)
        self.template_list.setMaximumWidth(250)
        self._populate_template_list("")
        self.template_list.itemClicked.connect(self.on_template_clicked)
        self.template_list.itemExpanded.connect(self.on_item_expanded_collapsed)
        self.template_list.itemCollapsed.connect(self.on_item_expanded_collapsed)
        self._last_toggled_time = 0
        self.template_panel.addWidget(self.template_list)
        
        template_container = QWidget()
        template_container.setLayout(self.template_panel)
        template_container.setMaximumWidth(250)
        self.layout.addWidget(template_container)

        # Right: Editor Area
        self.editor_layout = QVBoxLayout()
        self.right_container = QWidget()
        self.right_container_layout = QVBoxLayout(self.right_container)
        self.right_container_layout.setContentsMargins(0, 0, 0, 0)
        
        self.editor = CodeEditor()
        self.editor.setFont(QFont("Courier", 10))
        self.highlighter = PythonHighlighter(self.editor.document(), self.editor)
        self.editor.highlighter = self.highlighter

        self.top_layout = QHBoxLayout()
        
        # Left side: Choose Task label + dropdown
        self.choose_task_label = BodyLabel(self.tr("Choose Task:"))
        self.task_dropdown = ComboBox()
        self.task_dropdown.currentIndexChanged.connect(self.on_task_selected)
        
        # Right side: action buttons menu
        self.menu = RoundMenu(parent=self)
        
        self.save_action = Action(FluentIcon.SAVE, self.tr("Save"), shortcut='Ctrl+S')
        self.save_action.triggered.connect(self.save_code)
        self.menu.addAction(self.save_action)
        
        self.create_action = Action(FluentIcon.ADD, self.tr("Create Task"))
        self.create_action.triggered.connect(self.create_task)
        self.menu.addAction(self.create_action)
        
        self.copy_action = Action(FluentIcon.COPY, self.tr("Copy Task"))
        self.copy_action.triggered.connect(self.copy_task)
        self.menu.addAction(self.copy_action)
        
        self.delete_action = Action(FluentIcon.DELETE, self.tr("Delete Task"))
        self.delete_action.triggered.connect(self.delete_task)
        self.menu.addAction(self.delete_action)

        self.menu.addSeparator()

        self.export_action = Action(FluentIcon.SHARE, self.tr("Export Script"))
        self.export_action.triggered.connect(self.show_export_dialog)
        self.menu.addAction(self.export_action)

        self.import_action = Action(FluentIcon.DOWNLOAD, self.tr("Import Script"))
        self.import_action.triggered.connect(self.show_import_dialog)
        self.menu.addAction(self.import_action)

        self.file_button = TransparentDropDownPushButton(FluentIcon.MENU, self.tr("File"), self)
        self.file_button.setMenu(self.menu)
        
        self.top_layout.addWidget(self.choose_task_label)
        self.top_layout.addWidget(self.task_dropdown)
        self.top_layout.addWidget(self.file_button)
        
        # Spacer to push buttons to the right
        self.top_layout.addStretch(1)
        
        self.tools_layout = QHBoxLayout()
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(8)
        
        self.run_button = PrimaryPushButton(self)
        self.run_button.setText(self.tr("Run"))
        self.run_button.setIcon(FluentIcon.PLAY)
        self.run_button.clicked.connect(self.run_task)
        self.tools_layout.addWidget(self.run_button)

        self.record_button = PushButton(self)
        self.record_button.setText(self.tr("Record"))
        self.record_button.setIcon(FluentIcon.CAMERA)
        self.record_button.clicked.connect(self.toggle_record)
        self.tools_layout.addWidget(self.record_button)
        
        self.guide_button = PushButton(self)
        self.guide_button.setText(self.tr("Guide"))
        self.guide_button.setIcon(FluentIcon.HELP)
        self.guide_button.clicked.connect(self.open_guide)
        self.tools_layout.addWidget(self.guide_button)
        
        self.top_layout.addLayout(self.tools_layout)
        
        # Hide save and delete actions initially
        self.save_action.setVisible(False)
        self.delete_action.setVisible(False)

        self.right_container_layout.addLayout(self.top_layout)
        self.right_container_layout.addWidget(self.editor)
        
        self.error_label = BodyLabel()
        self.error_label.setStyleSheet("color: red;")
        self.error_label.setVisible(False)
        self.error_label.setWordWrap(True)
        self.right_container_layout.addWidget(self.error_label)
        
        self.empty_widget = QWidget()
        self.empty_layout = QVBoxLayout(self.empty_widget)
        self.empty_layout.setAlignment(Qt.AlignCenter)
        
        self.empty_buttons_layout = QHBoxLayout()
        self.empty_buttons_layout.setAlignment(Qt.AlignCenter)
        
        self.center_create_button = PrimaryPushButton(FluentIcon.ADD, self.tr("Create New Task"))
        self.center_create_button.clicked.connect(self.create_task)
        self.empty_buttons_layout.addWidget(self.center_create_button)
        
        self.center_copy_button = PushButton(FluentIcon.COPY, self.tr("Copy Task"))
        self.center_copy_button.clicked.connect(self.copy_task)
        self.empty_buttons_layout.addWidget(self.center_copy_button)
        
        self.empty_layout.addLayout(self.empty_buttons_layout)

        self.editor_layout.addWidget(self.right_container)
        self.editor_layout.addWidget(self.empty_widget)

        self.layout.addLayout(self.editor_layout)
        
        self.refresh_dropdown()

    def _update_error_display(self):
        if self.python_file and self.python_file in og.task_manager.task_errors:
            error_msg = og.task_manager.task_errors[self.python_file]
            self.error_label.setText(error_msg)
            self.error_label.setVisible(True)
            
            import re
            m = re.search(r'line (\d+)', error_msg.lower())
            if m:
                self.editor.set_error_line(int(m.group(1)))
            else:
                self.editor.set_error_line(-1)
        else:
            self.error_label.setVisible(False)
            if hasattr(self, 'editor') and hasattr(self.editor, 'set_error_line'):
                self.editor.set_error_line(-1)

    def _populate_template_list(self, query):
        self.template_list.clear()
        
        filtered = filter_templates(self.all_templates, query)
        
        groups = {}
        for t in filtered:
            cname = t.get('category', 'Other')
            if cname not in groups:
                groups[cname] = []
            groups[cname].append(t)
            
        categories_order = [
            "Mouse", "Key", "Control", "OCR", "Template Matching",
            "Box", "Window", "ADB", "Logging", "Other"
        ]

        category_translations = {
            "Mouse": self.tr("Mouse"),
            "Key": self.tr("Key"),
            "Control": self.tr("Control"),
            "OCR": self.tr("OCR"),
            "Template Matching": self.tr("Template Matching"),
            "Box": self.tr("Box"),
            "Window": self.tr("Window"),
            "ADB": self.tr("ADB"),
            "Logging": self.tr("Logging"),
            "Other": self.tr("Other"),
        }
        
        for cname in categories_order:
            if cname in groups:
                templates = groups[cname]
                display_name = category_translations.get(cname, cname)
                parent_item = QTreeWidgetItem([display_name])
                parent_item.setFlags(parent_item.flags() & ~Qt.ItemIsSelectable)
                self.template_list.addTopLevelItem(parent_item)
                
                for t in templates:
                    doc_preview = t.get('doc', '')
                    display_text = t['template_name']
                    if doc_preview:
                        display_text = f"{t['template_name']}"
                    item = QTreeWidgetItem([self.tr(display_text)])
                    item.setData(0, Qt.UserRole, t)
                    item.setToolTip(0, t.get('full_doc', t.get('doc', '')))
                    parent_item.addChild(item)
                    
        self.template_list.collapseAll()

    def on_search_changed(self, text):
        self._populate_template_list(text)

    def refresh_dropdown(self):
        self.task_dropdown.blockSignals(True)
        self.task_dropdown.clear()
        folder = og.task_manager.task_folder
        if folder and os.path.exists(folder):
            for file in os.listdir(folder):
                if file.endswith('.py'):
                    self.task_dropdown.addItem(os.path.splitext(file)[0], userData=os.path.join(folder, file))
        self.task_dropdown.blockSignals(False)
        
        has_tasks = self.task_dropdown.count() > 0
        if has_tasks:
            self.right_container.setVisible(True)
            self.empty_widget.setVisible(False)
            if not self.python_file:
                self.task_dropdown.setCurrentIndex(0)
                self.on_task_selected(0)
            else:
                # Reselect current item correctly
                for i in range(self.task_dropdown.count()):
                    if self.task_dropdown.itemData(i) == self.python_file:
                        self.task_dropdown.blockSignals(True)
                        self.task_dropdown.setCurrentIndex(i)
                        self._current_dropdown_index = i
                        self.task_dropdown.blockSignals(False)
                        break
        else:
            self.right_container.setVisible(False)
            self.empty_widget.setVisible(True)
            self.python_file = None
            self.task = None

    def on_task_selected(self, index):
        if hasattr(self, 'editor') and self.editor.document().isModified() and hasattr(self, 'python_file') and self.python_file:
            reply = QMessageBox.question(self, self.tr('Save Changes'),
                                         self.tr("The current task has unsaved changes. Do you want to save them?"),
                                         QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if reply == QMessageBox.Yes:
                if not self.save_code():
                    self._revert_dropdown_index()
                    return
            elif reply == QMessageBox.Cancel:
                self._revert_dropdown_index()
                return

        if index >= 0:
            self.python_file = self.task_dropdown.itemData(index)
            
            # Match task instance if exists
            self.task = None
            for t, data in og.task_manager.task_map.items():
                if data[0] == self.python_file:
                    self.task = t
                    break
            
            if self.python_file and os.path.exists(self.python_file):
                self.save_action.setVisible(True)
                self.delete_action.setVisible(True)
                with open(self.python_file, 'r', encoding='utf-8') as f:
                    self.editor.setPlainText(f.read())
                self.editor.document().setModified(False)
                self._update_file_watcher()
            else:
                self.save_action.setVisible(False)
                self.delete_action.setVisible(False)
                self.editor.clear()
                self.editor.document().setModified(False)
                self._update_file_watcher()
            self._update_error_display()
            self._current_dropdown_index = index

    def _revert_dropdown_index(self):
        if hasattr(self, '_current_dropdown_index'):
            self.task_dropdown.blockSignals(True)
            self.task_dropdown.setCurrentIndex(self._current_dropdown_index)
            self.task_dropdown.blockSignals(False)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_S:
            self.save_code()
            event.accept()
        else:
            super().keyPressEvent(event)

    def run_task(self):
        if self.save_code(silent=True):
            if self.python_file:
                for t, data in og.task_manager.task_map.items():
                    if data[0] == self.python_file:
                        self._switch_to_task_tab() # Switch first for immediate UI response
                        og.app.start_controller.start(t) # Launch asynchronously via start_controller
                        return

    def _switch_to_task_tab(self):
        """Switch to the tab that contains the current task."""
        if not self.task:
            return
        try:
            main_window = og.main_window
            # Check if task is in onetime_tab
            if main_window.onetime_tab and main_window.onetime_tab.in_current_list(self.task):
                main_window.switchTo(main_window.onetime_tab)
                return
            # Check grouped tabs
            for group_tab in main_window.grouped_task_tabs:
                if group_tab.in_current_list(self.task):
                    main_window.switchTo(group_tab)
                    return
            # Check trigger_tab
            if main_window.trigger_tab and main_window.trigger_tab.in_current_list(self.task):
                main_window.switchTo(main_window.trigger_tab)
                return
            # Fallback: switch to onetime_tab if available
            if main_window.onetime_tab:
                main_window.switchTo(main_window.onetime_tab)
        except Exception as e:
            logger.error(f"Error switching tab: {e}")

    def open_guide(self):
        QDesktopServices.openUrl(QUrl("https://github.com/ok-oldking/ok-py"))

    def toggle_record(self):
        from .RecordScript import recorder
        from qfluentwidgets import MessageBoxBase, SubtitleLabel, BodyLabel, ComboBox, SpinBox
        
        if not recorder.is_recording:
            parent_tab = self
            
            class RecordTaskDialog(MessageBoxBase):
                def __init__(self, parent=None):
                    super().__init__(parent)
                    self.titleLabel = SubtitleLabel(parent_tab.tr('Warning'), self)
                    self.msgLabel = BodyLabel(parent_tab.tr("Record will override the current script logic. Continue?"), self)
                    
                    self.loop_combo = ComboBox(self)
                    self.loop_combo.addItem(parent_tab.tr("No loop"))
                    self.loop_combo.addItem(parent_tab.tr("Loop x times"))
                    self.loop_combo.addItem(parent_tab.tr("Loop infinitely"))
                    
                    self.loop_count_input = SpinBox(self)
                    self.loop_count_input.setMinimum(1)
                    self.loop_count_input.setMaximum(999999)
                    self.loop_count_input.setValue(10)
                    self.loop_count_input.setVisible(False)
                    
                    self.loop_combo.currentIndexChanged.connect(self.on_combo_changed)
                    
                    self.viewLayout.addWidget(self.titleLabel)
                    self.viewLayout.addWidget(self.msgLabel)
                    self.viewLayout.addWidget(self.loop_combo)
                    self.viewLayout.addWidget(self.loop_count_input)
                    
                    self.yesButton.setText(parent_tab.tr('OK'))
                    self.cancelButton.setText(parent_tab.tr('Cancel'))
                    self.widget.setMinimumWidth(360)
                    
                def on_combo_changed(self, index):
                    self.loop_count_input.setVisible(index == 1)

            w = RecordTaskDialog(self.window())
            if w.exec():
                self._record_loop_type = w.loop_combo.currentIndex()
                if self._record_loop_type == 1:
                    self._record_loop_count = w.loop_count_input.value()
                        
                hwnd_name = og.device_manager.get_hwnd_name()
                from ok.gui.util.Alert import alert_info
                alert_msg = parent_tab.tr("Recording will start when window '{hwnd_name}' becomes active.")
                alert_info(alert_msg.replace("{hwnd_name}", hwnd_name))
                
                recorder.start(hwnd_name)
                
                self.run_button.setText(self.tr("Stop"))
                self.run_button.setIcon(FluentIcon.PAUSE)
                self.run_button.clicked.disconnect()
                self.run_button.clicked.connect(self.toggle_record)
                self.record_button.setVisible(False)
        else:
            init_code, run_code = recorder.stop()
            
            loop_type = getattr(self, '_record_loop_type', 0)
            if loop_type == 1:
                loop_count = getattr(self, '_record_loop_count', 1)
                new_run_code = []
                new_run_code.append(f"for _ in range({loop_count}):")
                run_code_lines = [line for line in run_code.strip('\n').split('\n') if line.strip()]
                if not run_code_lines:
                    new_run_code.append("    pass")
                else:
                    for line in run_code_lines:
                        new_run_code.append("    " + line)
                run_code = "\n".join(new_run_code)
            elif loop_type == 2:
                new_run_code = []
                new_run_code.append("while True:")
                run_code_lines = [line for line in run_code.strip('\n').split('\n') if line.strip()]
                if not run_code_lines:
                    new_run_code.append("    pass")
                else:
                    for line in run_code_lines:
                        new_run_code.append("    " + line)
                run_code = "\n".join(new_run_code)
                
            self.run_button.setText(self.tr("Run"))
            self.run_button.setIcon(FluentIcon.PLAY)
            self.run_button.clicked.disconnect()
            self.run_button.clicked.connect(self.run_task)
            self.record_button.setVisible(True)
            self._replace_run_block(init_code, run_code)

    def _replace_run_block(self, init_code, run_code):
        import re
        code = self.editor.toPlainText()
        
        lines = code.split('\n')
        
        # 1. Replace capture_config in __init__
        if init_code:
            init_start = -1
            init_indentation = ""
            for i, line in enumerate(lines):
                if re.match(r'^\s*def\s+__init__\s*\(.*?\)\s*:', line):
                    init_start = i
                    match = re.match(r'^(\s*)def', line)
                    base_indent = match.group(1) if match else ""
                    init_indentation = base_indent + "    "
                    break
                    
            if init_start != -1:
                capture_config_start = -1
                capture_config_end = -1
                
                for i in range(init_start + 1, len(lines)):
                    if re.match(r'^\s*def\s+', lines[i]) or (lines[i].strip() and not lines[i].startswith(init_indentation)):
                        break
                        
                    if re.match(r'^\s*self\.capture_config\s*=', lines[i]):
                        capture_config_start = i
                        brackets = 0
                        for j in range(i, len(lines)):
                            if j > i and (re.match(r'^\s*def\s+', lines[j]) or (lines[j].strip() and not lines[j].startswith(init_indentation))):
                                capture_config_end = j - 1
                                break
                            brackets += lines[j].count('{') - lines[j].count('}')
                            if brackets <= 0:
                                capture_config_end = j
                                break
                        if capture_config_end == -1:
                            capture_config_end = i
                        break
                        
                init_lines = init_code.strip('\n').split('\n')
                formatted_init_code = []
                for line in init_lines:
                    formatted_init_code.append(init_indentation + line.rstrip())
                    
                if capture_config_start != -1 and capture_config_end != -1:
                    lines = lines[:capture_config_start] + formatted_init_code + lines[capture_config_end + 1:]
                else:
                    insert_idx = init_start + 1
                    for i in range(init_start + 1, len(lines)):
                        if re.match(r'^\s*def\s+', lines[i]) or (lines[i].strip() and not lines[i].startswith(init_indentation)):
                            break
                        insert_idx = i + 1
                    lines = lines[:insert_idx] + formatted_init_code + lines[insert_idx:]

        # 2. Replace run method body
        run_start = -1
        indentation = ""
        for i, line in enumerate(lines):
            if re.match(r'^\s*def\s+run\s*\(.*?\)\s*:', line):
                run_start = i
                match = re.match(r'^(\s*)def', line)
                base_indent = match.group(1) if match else ""
                indentation = base_indent + "    "
                break
                
        if run_start != -1:
            run_end = len(lines)
            for i in range(run_start + 1, len(lines)):
                if re.match(r'^\s*def\s+', lines[i]) or (lines[i].strip() and not lines[i].startswith(indentation)):
                    run_end = i
                    break
                    
            new_lines = lines[:run_start+1]
            generated_code_lines = run_code.strip('\n').split('\n')
            for line in generated_code_lines:
                new_lines.append(indentation + line.rstrip())
            new_lines.extend(lines[run_end:])
            
            cursor = self.editor.textCursor()
            v_scroll = self.editor.verticalScrollBar().value()
            
            self.editor.setPlainText("\n".join(new_lines))
            self.editor.verticalScrollBar().setValue(v_scroll)

    def save_code(self, silent=False):
        code = self.editor.toPlainText()
        if self.python_file:
            try:
                with open(self.python_file, 'w', encoding='utf-8') as f:
                    f.write(code)
                self._last_mtime = os.path.getmtime(self.python_file)
                if self.task:
                    og.task_manager.reload_task_code(self.task)
                else:
                    og.task_manager.load_single_user_task(self.python_file)
                    
                self.task = None
                for t, data in og.task_manager.task_map.items():
                    if data[0] == self.python_file:
                        self.task = t
                        break

                self._update_error_display()
                
                # If there's an error, don't show success or switch tab
                if self.python_file in og.task_manager.task_errors:
                    return False

                self.editor.document().setModified(False)
                if not silent:
                    from ok.gui.util.app import show_info_bar
                    show_info_bar(self.window(), self.tr("Task rebuilt successfully."), title=self.tr("Success"))
                return True
            except Exception as e:
                from ok.gui.util.Alert import alert_error
                alert_error(f"{self.tr('Failed to save')}: {e}")
                return False
        return False

    def delete_task(self):
        if not self.python_file:
            return
            
        w = MessageBox(self.tr('Confirm Delete'), 
                       self.tr(f"Are you sure you want to delete {os.path.basename(self.python_file)}?"), 
                       self.window())
                                     
        if w.exec():
            try:
                if self.task:
                    og.task_manager.delete_task(self.task)
                else:
                    if os.path.exists(self.python_file):
                        os.remove(self.python_file)
                
                from ok.gui.util.app import show_info_bar
                show_info_bar(self.window(), self.tr("Task deleted successfully."), title=self.tr("Success"))
                self.python_file = None
                self.task = None
                self.editor.clear()
                self.refresh_dropdown()
            except Exception as e:
                from ok.gui.util.Alert import alert_error
                alert_error(f"Error deleting task: {e}")

    def on_item_expanded_collapsed(self, item):
        import time
        self._last_toggled_time = time.time()

    def on_template_clicked(self, item, column):
        import time
        template = item.data(0, Qt.UserRole)
        if not template:
            # If the item was expanded/collapsed natively by the chevron just now, don't revert it
            if time.time() - getattr(self, '_last_toggled_time', 0) < 0.1:
                return
            if item.isExpanded():
                item.setExpanded(False)
            else:
                item.setExpanded(True)
            return
        code_to_insert = TemplateFactory.handle_template(template, self)
        
        if code_to_insert:
            cursor = self.editor.textCursor()
            # Determine proper indentation
            block = cursor.block()
            line_text = block.text()
            indent_spaces = len(line_text) - len(line_text.lstrip(' '))
            
            # If the current line is completely empty, fallback to basic indent (e.g., 8 spaces) if inside a function
            if not line_text:
                indent_spaces = max(8, indent_spaces)
                
            indent_str = ' ' * indent_spaces
            
            # Format the insertion
            if line_text.strip():
                # If there is already code on this line, insert a new line with indentation
                final_text = f"\n{indent_str}{code_to_insert}\n"
            else:
                # If the line is empty, just insert the code with correct indentation
                if len(line_text) < indent_spaces:
                    # Pad the missing spaces if needed
                    final_text = (' ' * (indent_spaces - len(line_text))) + code_to_insert + "\n"
                else:
                    final_text = code_to_insert + "\n"
                    
            cursor.insertText(final_text)
            self.editor.setFocus()

    def create_task(self):
        from qfluentwidgets import MessageBoxBase, LineEdit, SubtitleLabel
        from ok.gui.util.Alert import alert_error
        import re

        class CreateTaskDialog(MessageBoxBase):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel(self.tr('Create Task'), self)
                
                self.class_name_input = LineEdit(self)
                self.class_name_input.setPlaceholderText(self.tr("Class Name (English only)"))
                
                self.task_name_input = LineEdit(self)
                self.task_name_input.setPlaceholderText(self.tr("Task Name"))
                
                self.task_desc_input = LineEdit(self)
                self.task_desc_input.setPlaceholderText(self.tr("Description (Optional)"))
                
                self.viewLayout.addWidget(self.titleLabel)
                self.viewLayout.addWidget(self.class_name_input)
                self.viewLayout.addWidget(self.task_name_input)
                self.viewLayout.addWidget(self.task_desc_input)
                self.yesButton.setText(self.tr('Confirm'))
                self.cancelButton.setText(self.tr('Cancel'))
                self.widget.setMinimumWidth(360)

        dialog = CreateTaskDialog(self.window())
        
        if dialog.exec():
            class_name = dialog.class_name_input.text().strip()
            task_name = dialog.task_name_input.text().strip()
            task_desc = dialog.task_desc_input.text().strip()
            
            if not class_name or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', class_name):
                alert_error(self.tr("Invalid Class Name. Must be English characters only."))
                return
            if not task_name:
                alert_error(self.tr("Task Name is required."))
                return

            base_class = "BaseTask"  # Defaulting to BaseTask for custom tasks
            
            task_code = f"""from ok import {base_class}

class {class_name}({base_class}):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "{task_name}"
        self.description = "{task_desc}"
        self.instructions = \"\"\"<a href="https://github.com/ok-oldking/ok-py">ok-py</a>\"\"\"

    def run(self):
        pass
"""
            file_path = os.path.join(og.task_manager.task_folder, f"{class_name}.py")
            if os.path.exists(file_path):
                alert_error(self.tr("Task file already exists."))
                return
                
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(task_code)
                self.refresh_dropdown()
                
                # Auto select the newly created task
                for i in range(self.task_dropdown.count()):
                    if self.task_dropdown.itemData(i) == file_path:
                        self.task_dropdown.setCurrentIndex(i)
                        break
                        
                og.task_manager.load_single_user_task(file_path)
                from ok.gui.util.app import show_info_bar
                show_info_bar(self.window(), self.tr("Task created successfully."), title=self.tr("Success"))
            except Exception as e:
                alert_error(f"Error creating task: {e}")

    def copy_task(self):
        from qfluentwidgets import MessageBoxBase, ComboBox, SubtitleLabel
        from ok.gui.util.Alert import alert_error
        import inspect

        class CopyTaskDialog(MessageBoxBase):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel(self.tr('Copy Task'), self)
                self.task_dropdown = ComboBox(self)
                self.task_dropdown.setPlaceholderText(self.tr("Select task to copy..."))
                
                self.tasks = []
                for task in og.task_manager.task_executor.onetime_tasks + og.task_manager.task_executor.trigger_tasks:
                    if task not in self.tasks:
                        self.tasks.append(task)
                        
                for task in og.task_manager.task_map.keys():
                    if task not in self.tasks:
                        self.tasks.append(task)
                        
                for task in self.tasks:
                    name = getattr(task, 'name', task.__class__.__name__)
                    class_name = task.__class__.__name__
                    display_text = f"{name} ({class_name})" if name != class_name else name
                    self.task_dropdown.addItem(display_text, userData=task)
                
                self.viewLayout.addWidget(self.titleLabel)
                self.viewLayout.addWidget(self.task_dropdown)
                self.yesButton.setText(self.tr('Confirm'))
                self.cancelButton.setText(self.tr('Cancel'))
                self.widget.setMinimumWidth(360)

        dialog = CopyTaskDialog(self.window())
        
        if dialog.exec():
            selected_task = dialog.task_dropdown.currentData()
            if not selected_task:
                return
                
            python_file, _ = og.task_manager.task_map.get(selected_task, (None, None))
            if not python_file or not os.path.exists(python_file):
                try:
                    python_file = inspect.getsourcefile(selected_task.__class__)
                except TypeError:
                    python_file = None
                    
            if not python_file or not os.path.exists(python_file):
                alert_error(self.tr(f"Could not find source file for {selected_task.__class__.__name__}"))
                return
                
            try:
                with open(python_file, "r", encoding="utf-8") as f:
                    source_code = f.read()
            except Exception as e:
                alert_error(self.tr(f"Failed to read source file: {e}"))
                return
                
            import re
            new_source = re.sub(
                r'(self\.name\s*=\s*)(self\.tr\(\s*)?(["\'])(.*?)\3(\))?',
                lambda m: f'{m.group(1)}{m.group(2) or ""}{m.group(3)}{m.group(4)}_copy{m.group(3)}{m.group(5) or ""}',
                source_code
            )
            
            base_name = os.path.basename(python_file)
            name_root, ext = os.path.splitext(base_name)
            
            new_file_name = f"{name_root}{ext}"
            counter = 1
            while os.path.exists(os.path.join(og.task_manager.task_folder, new_file_name)):
                new_file_name = f"{name_root}_{counter}{ext}"
                counter += 1
                
            target_path = os.path.join(og.task_manager.task_folder, new_file_name)
            
            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(new_source)
                self.refresh_dropdown()
                
                for i in range(self.task_dropdown.count()):
                    if self.task_dropdown.itemData(i) == target_path:
                        self.task_dropdown.setCurrentIndex(i)
                        break
                        
                og.task_manager.load_single_user_task(target_path)
                from ok.gui.util.app import show_info_bar
                show_info_bar(self.window(), self.tr("Task copied successfully."), title=self.tr("Success"))
            except Exception as e:
                alert_error(f"Error copying task: {e}")

    def show_export_dialog(self):
        from qfluentwidgets import MessageBoxBase, LineEdit, SubtitleLabel
        from ok.gui.util.Alert import alert_error
        from ok.gui.tasks.ScriptPackager import get_task_files, load_manifest, export_script, validate_filename

        task_files = get_task_files()
        if not task_files:
            alert_error(self.tr("No tasks to export."))
            return

        manifest = load_manifest()
        parent = self

        class ExportScriptDialog(MessageBoxBase):
            def __init__(self, p=None):
                super().__init__(p)
                self.titleLabel = SubtitleLabel(parent.tr('Export Script'), self)
                self.viewLayout.addWidget(self.titleLabel)

                # Task checkboxes
                self.task_label = BodyLabel(parent.tr('Select tasks to export:'), self)
                self.viewLayout.addWidget(self.task_label)

                self.checkboxes = []
                for tf in task_files:
                    cb = CheckBox(os.path.splitext(tf)[0], self)
                    cb.setChecked(True)
                    cb.setProperty('filename', tf)
                    self.viewLayout.addWidget(cb)
                    self.checkboxes.append(cb)

                # File name
                self.file_name_label = BodyLabel(parent.tr('File Name:'), self)
                self.viewLayout.addWidget(self.file_name_label)
                self.file_name_input = LineEdit(self)
                self.file_name_input.setPlaceholderText(parent.tr('English, numbers and valid filename chars only'))
                self.file_name_input.setText(manifest.get('file_name', ''))
                self.viewLayout.addWidget(self.file_name_input)

                # Script name
                self.script_name_label = BodyLabel(parent.tr('Script Name:'), self)
                self.viewLayout.addWidget(self.script_name_label)
                self.script_name_input = LineEdit(self)
                self.script_name_input.setPlaceholderText(parent.tr('Display name for the script'))
                self.script_name_input.setText(manifest.get('script_name', ''))
                self.viewLayout.addWidget(self.script_name_input)

                # Version
                self.version_label = BodyLabel(parent.tr('Version:'), self)
                self.viewLayout.addWidget(self.version_label)
                self.version_input = LineEdit(self)
                self.version_input.setPlaceholderText('1.0.0')
                self.version_input.setText(manifest.get('version', '1.0.0'))
                self.viewLayout.addWidget(self.version_input)

                self.yesButton.setText(parent.tr('Export'))
                self.cancelButton.setText(parent.tr('Cancel'))
                self.widget.setMinimumWidth(400)

        dialog = ExportScriptDialog(self.window())

        if dialog.exec():
            file_name = dialog.file_name_input.text().strip()
            script_name = dialog.script_name_input.text().strip()
            version = dialog.version_input.text().strip()

            if not validate_filename(file_name):
                alert_error(self.tr('Invalid file name. Use English letters, numbers, underscores, hyphens only.'))
                return

            if not script_name:
                alert_error(self.tr('Script name is required.'))
                return

            selected = [cb.property('filename') for cb in dialog.checkboxes if cb.isChecked()]
            if not selected:
                alert_error(self.tr('Please select at least one task to export.'))
                return

            success, message, output_path = export_script(selected, file_name, script_name, version)
            if success:
                from ok.gui.util.app import show_info_bar
                show_info_bar(self.window(), self.tr('Script exported successfully to Downloads folder.'), title=self.tr('Success'))
                # Open Explorer and select the file
                import subprocess
                subprocess.Popen(f'explorer /select,"{os.path.normpath(output_path)}"')
            else:
                alert_error(f"{self.tr('Export failed')}: {message}")

    def show_import_dialog(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr('Select Script File'), '',
            self.tr('OKScript Files (*.okscript);;All Files (*)')
        )

        if not file_path:
            return

        self._show_import_warning(file_path)

    def _show_import_warning(self, file_path):
        from qfluentwidgets import MessageBoxBase, SubtitleLabel, BodyLabel, CheckBox
        from PySide6.QtCore import QTimer
        
        class ImportWarningDialog(MessageBoxBase):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel(self.tr('Warning'), self)
                self.viewLayout.addWidget(self.titleLabel)

                warning_text = self.tr('Make sure that you trust the script publisher, unverified script can and not limited to steal your account/ data money, destroy your data, harm/ controlling your computer.')
                self.warning_label = BodyLabel(warning_text, self)
                self.warning_label.setWordWrap(True)
                self.warning_label.setStyleSheet("color: red; font-weight: bold;")
                self.viewLayout.addWidget(self.warning_label)
                
                self.check_box = CheckBox(self.tr('I understand the risks and want to import this script.'), self)
                self.viewLayout.addWidget(self.check_box)

                self.countdown = 15
                self.yesButton.setText(self.tr('Confirm') + f' ({self.countdown})')
                self.yesButton.setEnabled(False)
                
                self.cancelButton.setText(self.tr('Cancel'))
                self.widget.setMinimumWidth(400)
                
                self.timer = QTimer(self)
                self.timer.timeout.connect(self.update_countdown)
                self.timer.start(1000)
                
                self.check_box.stateChanged.connect(self.check_state_changed)
                
            def update_countdown(self):
                self.countdown -= 1
                if self.countdown > 0:
                    self.yesButton.setText(self.tr('Confirm') + f' ({self.countdown})')
                else:
                    self.timer.stop()
                    self.yesButton.setText(self.tr('Confirm'))
                    self.check_state_changed()

            def check_state_changed(self):
                if self.countdown <= 0 and self.check_box.isChecked():
                    self.yesButton.setEnabled(True)
                else:
                    self.yesButton.setEnabled(False)
                    
        dialog = ImportWarningDialog(self.window())
        if dialog.exec():
            self._do_import(file_path)

    def _do_import(self, file_path):
        from ok.gui.util.Alert import alert_error
        from ok.gui.tasks.ScriptPackager import import_script

        success, message, import_folder = import_script(file_path)
        if success:
            from ok.gui.util.app import show_info_bar
            show_info_bar(self.window(), message, title=self.tr('Success'))
            # Load the imported tasks
            og.task_manager.load_import_folder(import_folder)
        else:
            alert_error(f"{self.tr('Import failed')}: {message}")
