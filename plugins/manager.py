import importlib
import inspect
import pkgutil
from typing import Dict, Type, Optional
from urllib.parse import urlparse
import plugins
from .base import ATSPluginInterface

class PluginManager:
    """Manages dynamic discovery and routing of ATS plugins."""
    
    def __init__(self):
        self._plugins: Dict[str, ATSPluginInterface] = {}
        self._load_plugins()

    def _load_plugins(self):
        """Scans the plugins directory and registers any ATSPluginInterface subclass."""
        # Iterate over modules in the 'plugins' package
        for _, module_name, is_pkg in pkgutil.iter_modules(plugins.__path__):
            # Skip base definitions and subpackages
            if module_name in ('base', 'manager') or is_pkg:
                continue
            
            full_module_name = f"plugins.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
                
                # Find classes in the module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # Register classes that inherit from ATSPluginInterface
                    if issubclass(obj, ATSPluginInterface) and obj is not ATSPluginInterface:
                        try:
                            # Instantiate the plugin globally
                            instance = obj()
                            self._plugins[instance.portal_name] = instance
                        except TypeError as e:
                            print(f"[ERROR] Failed to instantiate {name}. Missing abstract methods? {e}")
            except Exception as e:
                print(f"[ERROR] Failed to load plugin module '{module_name}': {e}")

    def get_plugin_for_url(self, url: str) -> Optional[ATSPluginInterface]:
        """Iterates through registered plugins and matches the URL domain."""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
        except Exception:
            netloc = url.lower()
            
        for name, plugin in self._plugins.items():
            for matcher in plugin.domain_matchers:
                if matcher.lower() in netloc or matcher.lower() in url.lower():
                    return plugin
        return None

    def get_all_plugins(self) -> Dict[str, ATSPluginInterface]:
        """Returns the dictionary mapping portal_name -> PluginInstance"""
        return self._plugins
