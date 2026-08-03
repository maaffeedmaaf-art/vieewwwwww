"""
Stubs Kivy so main.py can be imported on a plain CI runner.

main.py imports Kivy at module scope, and Kivy needs a display and a long
list of system libraries. None of the logic under test touches the widget
toolkit, so we install lightweight fakes into sys.modules before import.
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class FakeWidget:
    """Accepts any constructor kwargs and any attribute assignment."""

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.text = kw.get("text", "")
        self.values = kw.get("values", [])
        self.children = []

    def bind(self, **kw):
        pass

    def add_widget(self, widget):
        self.children.append(widget)


class FakeClock:
    @staticmethod
    def schedule_once(fn, timeout=0):
        fn(0)


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _install_kivy_stubs():
    for pkg in ("kivy", "kivy.uix", "kivy.core"):
        _module(pkg)
    _module("kivy.app",
            App=type("App", (), {"get_running_app": staticmethod(lambda: None)}))
    _module("kivy.clock", Clock=FakeClock)
    _module("kivy.core.text",
            LabelBase=type("LabelBase", (),
                           {"register": staticmethod(lambda *a, **k: None)}),
            DEFAULT_FONT="Roboto")
    _module("kivy.core.window", Window=types.SimpleNamespace())
    _module("kivy.metrics", dp=lambda value: value)
    _module("kivy.uix.boxlayout", BoxLayout=FakeWidget)
    _module("kivy.uix.button", Button=FakeWidget)
    _module("kivy.uix.label", Label=FakeWidget)
    _module("kivy.uix.screenmanager", Screen=FakeWidget,
            ScreenManager=FakeWidget, SlideTransition=lambda **k: None)
    _module("kivy.uix.scrollview", ScrollView=FakeWidget)
    _module("kivy.uix.spinner", Spinner=FakeWidget)
    _module("kivy.uix.textinput", TextInput=FakeWidget)


# ANDROID_ARGUMENT must be absent so main.py takes the desktop code path
os.environ.pop("ANDROID_ARGUMENT", None)
_install_kivy_stubs()
