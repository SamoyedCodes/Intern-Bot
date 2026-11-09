"""Control-key editing aliases alongside macOS's native Command shortcuts."""
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit


class EditShortcuts(QObject):
    def follow_focus(self, previous, current):
        # Embedded Chromium owns native objects that are unsafe to wrap in a global Qt event filter.
        for widget in (previous, current):
            editor = widget.lineEdit() if isinstance(widget, QComboBox) else widget
            if isinstance(editor, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractItemView)):
                if widget is previous:
                    editor.removeEventFilter(self)
                else:
                    editor.installEventFilter(self)

    def eventFilter(self, editor, event):
        if event.type() not in {QEvent.ShortcutOverride, QEvent.KeyPress} or not isinstance(editor, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractItemView)):
            return False
        # Qt names the physical Control key Meta on macOS; Control is the Command key.
        modifiers = event.modifiers()
        if modifiers not in {Qt.MetaModifier, Qt.MetaModifier | Qt.ShiftModifier}:
            return False
        key, shift = event.key(), bool(modifiers & Qt.ShiftModifier)
        action = {Qt.Key_A: 'selectAll', Qt.Key_C: 'copy', Qt.Key_X: 'cut', Qt.Key_V: 'paste', Qt.Key_Z: 'redo' if shift else 'undo', Qt.Key_Y: 'redo'}.get(key)
        words = key in {Qt.Key_Left, Qt.Key_Right, Qt.Key_Backspace, Qt.Key_Delete}
        if isinstance(editor, QAbstractItemView):
            if action != 'selectAll' or shift:
                return False
        elif not action and not words:
            return False
        if shift and key not in {Qt.Key_Z, Qt.Key_Left, Qt.Key_Right}:
            return False
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        if isinstance(editor, (QLineEdit, QPlainTextEdit, QTextEdit)) and editor.isReadOnly() and (action in {'cut', 'paste', 'undo', 'redo'} or key in {Qt.Key_Backspace, Qt.Key_Delete}):
            event.accept()
            return True
        if action:
            getattr(editor, action)()
        elif isinstance(editor, QLineEdit):
            deleting = key in {Qt.Key_Backspace, Qt.Key_Delete}
            if not deleting or not editor.hasSelectedText():
                move = editor.cursorWordBackward if key in {Qt.Key_Left, Qt.Key_Backspace} else editor.cursorWordForward
                move(shift or deleting)
            if deleting and not editor.isReadOnly():
                editor.backspace()
        else:
            cursor = editor.textCursor()
            deleting = key in {Qt.Key_Backspace, Qt.Key_Delete}
            if deleting and editor.isReadOnly():
                return True
            if not deleting or not cursor.hasSelection():
                direction = QTextCursor.PreviousWord if key in {Qt.Key_Left, Qt.Key_Backspace} else QTextCursor.NextWord
                cursor.movePosition(direction, QTextCursor.KeepAnchor if shift or deleting else QTextCursor.MoveAnchor)
            if deleting:
                cursor.removeSelectedText()
            editor.setTextCursor(cursor)
        event.accept()
        return True


def install_edit_shortcuts(app):
    if sys.platform == 'darwin' and not hasattr(app, '_edit_shortcuts'):
        app._edit_shortcuts = EditShortcuts(app)
        app.focusChanged.connect(app._edit_shortcuts.follow_focus)
        app._edit_shortcuts.follow_focus(None, app.focusWidget())
