"""Both physical Control aliases and native Command editing work in the desktop's editors."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QMimeData, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

import gui.shortcuts as shortcuts


@pytest.fixture(autouse=True)
def editing_shortcuts(qt_app, monkeypatch):
    # Test macOS's modifier mapping consistently, including on non-macOS CI.
    monkeypatch.setattr(shortcuts, 'sys', SimpleNamespace(platform='darwin'))
    shortcuts.install_edit_shortcuts(qt_app)
    clipboard = qt_app.clipboard()
    saved = QMimeData()
    for fmt in clipboard.mimeData().formats() if clipboard.mimeData() else []:
        saved.setData(fmt, clipboard.mimeData().data(fmt))
    yield
    if saved.formats():
        clipboard.setMimeData(saved)
    else:
        clipboard.clear()


@pytest.fixture(params=[QLineEdit, QPlainTextEdit, QTextEdit])
def editor(request):
    widget = request.param()
    widget.show()
    widget.setFocus()
    QApplication.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def set_text(editor, text):
    editor.setText(text) if isinstance(editor, QLineEdit) else editor.setPlainText(text)


def text(editor):
    return editor.text() if isinstance(editor, QLineEdit) else editor.toPlainText()


def selected(editor):
    return editor.selectedText() if isinstance(editor, QLineEdit) else editor.textCursor().selectedText()


def position(editor, value=None):
    if value is not None:
        if isinstance(editor, QLineEdit):
            editor.setCursorPosition(value)
        else:
            cursor = editor.textCursor()
            cursor.setPosition(value)
            editor.setTextCursor(cursor)
    return editor.cursorPosition() if isinstance(editor, QLineEdit) else editor.textCursor().position()


@pytest.mark.parametrize('modifier', [Qt.ControlModifier, Qt.MetaModifier], ids=['command', 'physical-control'])
def test_select_copy_cut_paste_undo_and_redo(editor, modifier):
    set_text(editor, 'first second')
    QTest.keyClick(editor, Qt.Key_A, modifier)
    assert selected(editor) == 'first second'
    QTest.keyClick(editor, Qt.Key_C, modifier)
    assert QApplication.clipboard().text() == 'first second'
    QTest.keyClick(editor, Qt.Key_X, modifier)
    assert text(editor) == ''
    QTest.keyClick(editor, Qt.Key_V, modifier)
    assert text(editor) == 'first second'
    QTest.keyClick(editor, Qt.Key_Z, modifier)
    assert text(editor) == ''
    QTest.keyClick(editor, Qt.Key_Z, modifier | Qt.ShiftModifier)
    assert text(editor) == 'first second'


def test_holding_control_moves_selects_and_deletes_words(editor):
    set_text(editor, 'first second third')
    position(editor, 0)
    QTest.keyClick(editor, Qt.Key_Right, Qt.MetaModifier)
    assert position(editor) == 6
    # Repeated presses while the modifier stays held must keep moving by whole words.
    QApplication.sendEvent(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.MetaModifier, '', True, 1))
    assert position(editor) == 13
    QTest.keyClick(editor, Qt.Key_Left, Qt.MetaModifier | Qt.ShiftModifier)
    assert selected(editor) == 'second '
    QTest.keyClick(editor, Qt.Key_Backspace, Qt.MetaModifier)
    assert text(editor) == 'first third'
    position(editor, 0)
    QTest.keyClick(editor, Qt.Key_Delete, Qt.MetaModifier)
    assert text(editor) == 'third'
    QTest.keyClick(editor, Qt.Key_Z, Qt.MetaModifier)
    assert text(editor) == 'first third'


def test_read_only_editors_allow_select_and_copy_but_cannot_be_modified(editor):
    set_text(editor, 'original')
    position(editor, len(text(editor)))
    QTest.keyClicks(editor, ' addition')
    editor.setReadOnly(True)
    before = text(editor)
    QTest.keyClick(editor, Qt.Key_A, Qt.MetaModifier)
    QTest.keyClick(editor, Qt.Key_C, Qt.MetaModifier)
    assert QApplication.clipboard().text() == before
    for key in [Qt.Key_X, Qt.Key_V, Qt.Key_Z, Qt.Key_Y, Qt.Key_Backspace, Qt.Key_Delete]:
        QTest.keyClick(editor, key, Qt.MetaModifier)
        assert text(editor) == before


def test_password_copy_stays_protected_and_unmodified_typing_still_works(qt_app):
    editor = QLineEdit()
    editor.show()
    editor.setFocus()
    qt_app.processEvents()
    editor.setEchoMode(QLineEdit.Password)
    editor.setText('fixture password')
    qt_app.clipboard().setText('clipboard remains intact')
    QTest.keyClick(editor, Qt.Key_A, Qt.MetaModifier)
    QTest.keyClick(editor, Qt.Key_C, Qt.MetaModifier)
    assert qt_app.clipboard().text() == 'clipboard remains intact'
    QTest.keyClicks(editor, 'replacement')
    assert editor.text() == 'replacement'
    editor.close()


def test_editable_combobox_uses_the_same_shortcuts(qt_app):
    combo = QComboBox()
    combo.setEditable(True)
    combo.show()
    combo.setFocus()
    qt_app.processEvents()
    combo.setEditText('A long form option')
    QTest.keyClick(combo.lineEdit(), Qt.Key_A, Qt.MetaModifier)
    assert combo.lineEdit().selectedText() == 'A long form option'
    combo.close()


def test_installation_is_idempotent(qt_app):
    existing = qt_app._edit_shortcuts
    shortcuts.install_edit_shortcuts(qt_app)
    assert qt_app._edit_shortcuts is existing
