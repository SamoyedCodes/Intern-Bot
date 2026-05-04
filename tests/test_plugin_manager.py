from plugins.manager import PluginManager
from plugins.workday import WorkdayPlugin


def test_plugin_manager_routes_workday_urls():
    manager = PluginManager()

    plugin = manager.get_plugin_for_url("https://example.wd1.myworkdayjobs.com/job/intern")

    assert isinstance(plugin, WorkdayPlugin)


def test_plugin_manager_returns_none_for_unknown_domain():
    manager = PluginManager()

    plugin = manager.get_plugin_for_url("https://jobs.example.com/intern")

    assert plugin is None
