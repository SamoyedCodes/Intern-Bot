import asyncio
import inspect
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import keyring
import pytest

from core.browser.playwright_mgr import AsyncPlaywrightManager
from core.storage.local_store import LocalStore
from core.storage.vault import CredentialVault
from tests.support import EXTENSION, MemoryKeychain

# One loop runs every async test and browser fixture: Playwright objects belong to the loop that created them.
LOOP = asyncio.new_event_loop()
BROWSER_FIXTURES = {'extension_browser', 'context', 'fresh_context'}


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        LOOP.run_until_complete(pyfuncitem.obj(**{name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}))
        return True


def pytest_collection_modifyitems(items):
    for item in items:
        if BROWSER_FIXTURES & set(item.fixturenames):
            item.add_marker(pytest.mark.browser)


def pytest_sessionfinish():
    LOOP.close()


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    monkeypatch.setattr(keyring, 'get_keyring', lambda: pytest.fail('Tests must never touch the real OS keychain'))


@pytest.fixture
def vault():
    return CredentialVault(MemoryKeychain())


@pytest.fixture
def store(tmp_path, vault):
    return LocalStore(tmp_path / 'state.db', vault)


@pytest.fixture(scope='session')
def qt_app():
    from PySide6.QtWidgets import QApplication
    from gui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def window(qt_app, store, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from gui.main_window import MainWindow
    monkeypatch.chdir(tmp_path)
    window = MainWindow(store)
    yield window
    window.close()  # Also shuts down the window's automation service.
    # Delete it now: every live widget is re-polished whenever a later test restyles the app.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def start_browser(path):
    manager = AsyncPlaywrightManager(user_data_dir=str(path), extension_path=EXTENSION)
    return manager, LOOP.run_until_complete(manager.start())


@pytest.fixture(scope='module')
def extension_browser(tmp_path_factory):
    """One Chromium with the local extension, shared by a test module."""
    manager, context = start_browser(tmp_path_factory.mktemp('browser'))
    yield context
    LOOP.run_until_complete(manager.stop())


@pytest.fixture
def context(extension_browser):
    yield extension_browser
    # The extension only binds a uniquely open tab URL, so no test may leave pages behind.
    for page in extension_browser.pages[1:]:
        LOOP.run_until_complete(page.close())


@pytest.fixture
def fresh_context(tmp_path):
    """A dedicated browser for tests that restart the extension worker or attach to it."""
    manager, context = start_browser(tmp_path / 'browser')
    yield context
    LOOP.run_until_complete(manager.stop())
