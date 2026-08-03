# -*- coding: utf-8 -*-
"""
TG Stories — تطبيق أندرويد لتنزيل قصص تيليجرام بصفة مجهولة
"""

# ===========================================================================
# لاقط الأعطال — يجب أن يسبق استيراد Kivy.
# الانهيار يقع قبل ظهور أي شاشة، فلا تنفع شاشة خطأ داخل التطبيق.
# نوجّه stdout/stderr إلى ملف نصي يمكن فتحه بمدير الملفات.
# ===========================================================================
import os
import sys
import traceback

_LOG = None
LOG_PATH = "(none)"
for _base in ("/sdcard/Download",
              "/storage/emulated/0/Download",
              "/sdcard/Android/data/org.maaf.tgstories/files",
              "/data/data/org.maaf.tgstories/files"):
    try:
        os.makedirs(_base, exist_ok=True)
        _p = os.path.join(_base, "tgstories.log")
        _LOG = open(_p, "w", buffering=1, encoding="utf-8", errors="replace")
        LOG_PATH = _p
        break
    except Exception:
        _LOG = None

if _LOG:
    sys.stdout = sys.stderr = _LOG
    os.environ.setdefault("KIVY_HOME", os.path.join(os.path.dirname(LOG_PATH),
                                                    ".kivy_tgstories"))


def _log(msg):
    try:
        (_LOG or sys.__stderr__).write(str(msg) + "\n")
        (_LOG or sys.__stderr__).flush()
    except Exception:
        pass


def _hook(tp, val, tb):
    _log("=== UNCAUGHT ===")
    try:
        traceback.print_exception(tp, val, tb, file=_LOG or sys.__stderr__)
        (_LOG or sys.__stderr__).flush()
    except Exception:
        pass


sys.excepthook = _hook

# يلتقط الانهيارات الأصلية (SIGSEGV) التي لا يراها try/except
try:
    import faulthandler
    faulthandler.enable(file=_LOG or sys.__stderr__, all_threads=True)
except Exception:
    pass


def _thread_hook(args):
    _log("=== UNCAUGHT IN THREAD ===")
    try:
        traceback.print_exception(args.exc_type, args.exc_value,
                                  args.exc_traceback,
                                  file=_LOG or sys.__stderr__)
    except Exception:
        pass


_log("=== boot start ===")
_log("log file: " + LOG_PATH)
_log("python: " + sys.version)

import asyncio
import json
import threading
from pathlib import Path

try:
    threading.excepthook = _thread_hook
except Exception:
    pass

_log("step: stdlib imported")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase, DEFAULT_FONT
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

_log("step: kivy imported")

# ---------------------------------------------------------------------------
# الخط العربي + التشكيل ثنائي الاتجاه
# ---------------------------------------------------------------------------

FONT = str(Path(__file__).parent / "assets" / "NotoNaskhArabic-Regular.ttf")
try:
    if os.path.exists(FONT):
        LabelBase.register(DEFAULT_FONT, FONT)
        _log("step: font registered")
    else:
        _log("WARN: font missing at " + FONT)
except Exception:
    _log("WARN: font registration failed")
    traceback.print_exc()

try:
    import arabic_reshaper

    try:
        from bidi.algorithm import get_display
    except ImportError:
        from bidi import get_display

    def ar(text):
        """يصل الحروف العربية ويرتّبها من اليمين لليسار (Kivy لا يفعل ذلك تلقائيًا)."""
        try:
            return get_display(arabic_reshaper.reshape(str(text)))
        except Exception:
            return str(text)

except Exception:
    _log("WARN: arabic libs unavailable")

    def ar(text):
        return str(text)


_log("step: arabic ready")


# ---------------------------------------------------------------------------
# مسارات التخزين
# ---------------------------------------------------------------------------

ON_ANDROID = "ANDROID_ARGUMENT" in os.environ


def storage_paths():
    """
    يرجع (مجلد_الإعدادات، مجلد_التنزيلات) بلا أي استدعاء JNI.

    python-for-android يصدّر المسارات كمتغيّرات بيئة، فلا داعي للمرور
    بـ jnius أو android.storage — وهما مصدر انهيار أصلي لا يلتقطه
    try/except على بعض الأجهزة.
    """
    if not ON_ANDROID:
        base = Path.home() / ".tgstory"
        return base, base / "downloads"

    # ANDROID_ARGUMENT is the *source* dir (app/), which is not reliably
    # writable. Only ANDROID_PRIVATE / ANDROID_APP_PATH point at real
    # private storage, so never fall back to ANDROID_ARGUMENT here.
    private = None
    for var in ("ANDROID_PRIVATE", "ANDROID_APP_PATH"):
        v = os.environ.get(var)
        if v:
            private = Path(v)
            _log("storage: using $%s = %s" % (var, v))
            break
    if private is None:
        private = Path("/data/data/org.maaf.tgstories/files")
        _log("storage: falling back to hardcoded private dir")

    return private, pick_download_dir(private)


def pick_download_dir(private):
    """
    أول مجلد قابل للكتابة فعليًا.

    يُستدعى مرّة عند الإقلاع ومرّة بعد منح الأذونات: قبل المنح تفشل
    الكتابة في /sdcard ونسقط للمجلد الخاص، وبعده يصبح المجلد العام متاحًا.
    """
    if not ON_ANDROID:
        return Path(private) / "downloads"

    for cand in ("/sdcard/Download/TGStories",
                 "/storage/emulated/0/Download/TGStories",
                 str(Path(private) / "downloads")):
        try:
            d = Path(cand)
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".w"
            probe.write_text("1")
            probe.unlink()
            _log("storage: downloads -> " + cand)
            return d
        except Exception as e:
            _log("storage: %s unusable (%s)" % (cand, type(e).__name__))

    return Path(private)


# NOTE: these stay None until ensure_paths() runs from on_start().
# Calling request_permissions() at import time - before the Android
# activity exists - crashes the app before Kivy can show anything.
CONFIG_DIR = DOWNLOAD_DIR = CONFIG_FILE = SESSION_FILE = None


def ensure_paths():
    """Resolve storage locations. Safe to call more than once."""
    global CONFIG_DIR, DOWNLOAD_DIR, CONFIG_FILE, SESSION_FILE
    if CONFIG_DIR is not None:
        return
    CONFIG_DIR, DOWNLOAD_DIR = storage_paths()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE = CONFIG_DIR / "config.json"
    SESSION_FILE = CONFIG_DIR / "session.txt"


def refresh_download_dir():
    """يعيد اختيار مجلد التنزيل بعد منح الأذونات. يرجع True إن تغيّر."""
    global DOWNLOAD_DIR
    if CONFIG_DIR is None:
        return False
    new = pick_download_dir(CONFIG_DIR)
    if new != DOWNLOAD_DIR:
        DOWNLOAD_DIR = new
        _log("storage: downloads re-resolved -> %s" % new)
        return True
    return False


def load_config():
    ensure_paths()
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg):
    """يدمج المفاتيح الجديدة فوق القديمة بدل مسح الملف كاملًا."""
    ensure_paths()
    merged = load_config()
    merged.update(cfg)
    CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False),
                           encoding="utf-8")


# ---------------------------------------------------------------------------
# محرّك asyncio في thread منفصل
# ---------------------------------------------------------------------------

class AsyncWorker:
    """يشغّل حلقة asyncio في خيط خلفي، ويعيد النتائج لخيط Kivy بأمان."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, on_done=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if on_done:
            def _cb(f):
                Clock.schedule_once(lambda dt: on_done(f), 0)
            fut.add_done_callback(_cb)
        return fut


_WORKER = None
_WORKER_LOCK = threading.Lock()


class _LazyWorker:
    def submit(self, coro, on_done=None):
        global _WORKER
        with _WORKER_LOCK:
            if _WORKER is None:
                _WORKER = AsyncWorker()
            worker = _WORKER
        return worker.submit(coro, on_done)

    def run_sync(self, coro, timeout=10):
        """ينفّذ coroutine وينتظر نتيجتها — للإغلاق النظيف فقط."""
        with _WORKER_LOCK:
            if _WORKER is None:
                return None
            worker = _WORKER
        return worker.submit(coro).result(timeout)


WORKER = _LazyWorker()
_log("step: worker ready")


# ---------------------------------------------------------------------------
# عناصر واجهة مختصرة
# ---------------------------------------------------------------------------

BG = (0.08, 0.09, 0.12, 1)
ACCENT = (0.16, 0.55, 0.90, 1)
MUTED = (0.62, 0.66, 0.74, 1)


def L(text, size=16, color=(1, 1, 1, 1), bold=False, halign="right"):
    lbl = Label(
        text=ar(text), font_size=dp(size), color=color, bold=bold,
        halign=halign, valign="middle", size_hint_y=None,
    )
    lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
    lbl.bind(texture_size=lambda w, v: setattr(w, "height", v[1] + dp(6)))
    return lbl


def TI(hint="", password=False, numeric=False):
    return TextInput(
        hint_text=ar(hint), multiline=False, password=password,
        input_type="number" if numeric else "text",
        size_hint_y=None, height=dp(48), font_size=dp(17),
        padding=[dp(12), dp(12)], halign="left",
        background_color=(0.15, 0.17, 0.22, 1),
        foreground_color=(1, 1, 1, 1), cursor_color=ACCENT,
    )


def BTN(text, cb, color=ACCENT):
    b = Button(
        text=ar(text), size_hint_y=None, height=dp(50),
        font_size=dp(17), bold=True, background_normal="",
        background_color=color,
    )
    b.bind(on_release=cb)
    return b


def Pad(**kw):
    kw.setdefault("orientation", "vertical")
    kw.setdefault("padding", dp(20))
    kw.setdefault("spacing", dp(12))
    return BoxLayout(**kw)


def _err(exc):
    """رسالة خطأ قصيرة صالحة للعرض — النوع وحده لا يكفي للتشخيص."""
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if len(detail) > 90:
        detail = detail[:90] + "…"
    return "%s: %s" % (type(exc).__name__, detail) if detail \
        else type(exc).__name__


# ---------------------------------------------------------------------------
# شاشة ١ — إعداد مفاتيح الـ API
# ---------------------------------------------------------------------------

class SetupScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = Pad()
        root.add_widget(L("الإعداد الأولي", 26, bold=True))
        root.add_widget(L(
            "احصل على api_id و api_hash من my.telegram.org "
            "(سجّل الدخول ← API development tools)", 14, MUTED))
        root.add_widget(Label(size_hint_y=None, height=dp(8)))

        self.api_id = TI("api_id", numeric=True)
        self.api_hash = TI("api_hash")
        root.add_widget(self.api_id)
        root.add_widget(self.api_hash)
        root.add_widget(BTN("حفظ ومتابعة", self.save))

        self.msg = L("", 14, (1, 0.45, 0.45, 1))
        root.add_widget(self.msg)
        root.add_widget(Label())
        self.add_widget(root)

    def on_pre_enter(self, *_):
        """يملأ الحقول بالقيم المحفوظة حتى لا يعيد المستخدم كتابتها بعد فشل."""
        try:
            cfg = load_config()
        except Exception:
            return
        if cfg.get("api_id") and not self.api_id.text:
            self.api_id.text = str(cfg["api_id"])
        if cfg.get("api_hash") and not self.api_hash.text:
            self.api_hash.text = str(cfg["api_hash"])

    def save(self, *_):
        aid, ahash = self.api_id.text.strip(), self.api_hash.text.strip()
        if not aid.isdigit() or int(aid) <= 0:
            self.msg.text = ar("api_id يجب أن يكون رقمًا")
            return
        if len(ahash) != 32 or not all(c in "0123456789abcdefABCDEF"
                                       for c in ahash):
            self.msg.text = ar("api_hash يجب أن يكون 32 خانة ست عشرية")
            return
        self.msg.text = ""
        try:
            save_config({"api_id": int(aid), "api_hash": ahash})
        except Exception as e:
            self.msg.text = ar("تعذّر الحفظ: %s" % type(e).__name__)
            return
        App.get_running_app().boot_client()


# ---------------------------------------------------------------------------
# شاشة ٢ — تسجيل الدخول
# ---------------------------------------------------------------------------

class LoginScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.phone_hash = None
        root = Pad()
        root.add_widget(L("تسجيل الدخول", 26, bold=True))
        root.add_widget(L("رقمك يذهب لخوادم تيليجرام مباشرة فقط.", 14, MUTED))
        root.add_widget(Label(size_hint_y=None, height=dp(8)))

        self.phone = TI("+249xxxxxxxxx")
        self.send_btn = BTN("إرسال الكود", self.send_code)
        root.add_widget(self.phone)
        root.add_widget(self.send_btn)

        self.code = TI("الكود المُرسل", numeric=True)
        self.code.opacity = 0
        self.code.disabled = True
        self.pw = TI("كلمة مرور التحقق بخطوتين", password=True)
        self.pw.opacity = 0
        self.pw.disabled = True
        self.login_btn = BTN("دخول", self.sign_in, (0.15, 0.65, 0.42, 1))
        self.login_btn.opacity = 0
        self.login_btn.disabled = True

        root.add_widget(self.code)
        root.add_widget(self.pw)
        root.add_widget(self.login_btn)

        self.msg = L("", 14, (1, 0.55, 0.45, 1))
        root.add_widget(self.msg)
        root.add_widget(Label())
        self.add_widget(root)

    def _show(self, widget):
        widget.opacity = 1
        widget.disabled = False

    def send_code(self, *_):
        phone = self.phone.text.strip()
        if len(phone) < 8:
            self.msg.text = ar("أدخل رقمًا صحيحًا مع رمز الدولة")
            return
        app = App.get_running_app()
        if app.client is None:
            self.msg.text = ar("لا يوجد اتصال — أعد المحاولة")
            return
        self.send_btn.disabled = True
        self.msg.text = ar("جارٍ الإرسال ...")
        # كود قديم لم يعد صالحًا بعد طلب كود جديد
        self.phone_hash = None
        self.code.text = ""

        async def task():
            sent = await app.client.send_code_request(phone)
            return sent.phone_code_hash

        def done(fut):
            self.send_btn.disabled = False
            try:
                self.phone_hash = fut.result()
                self._show(self.code)
                self._show(self.login_btn)
                self.msg.text = ar("وصلك كود داخل تيليجرام — أدخله")
            except Exception as e:
                self.msg.text = ar("فشل الإرسال: %s" % _err(e))

        WORKER.submit(task(), done)

    def sign_in(self, *_):
        app = App.get_running_app()
        if app.client is None:
            self.msg.text = ar("لا يوجد اتصال — أعد المحاولة")
            return
        if not self.phone_hash:
            self.msg.text = ar("اطلب الكود أولًا")
            return
        phone = self.phone.text.strip()
        code = self.code.text.strip()
        pw = self.pw.text.strip()
        if not code and not pw:
            self.msg.text = ar("أدخل الكود المُرسل")
            return
        phone_hash = self.phone_hash
        self.login_btn.disabled = True
        self.msg.text = ar("جارٍ التحقق ...")

        async def task():
            from telethon.errors import SessionPasswordNeededError
            if pw:
                # الكود صار مستهلكًا في المحاولة الأولى؛ لم يبقَ إلا كلمة المرور
                await app.client.sign_in(password=pw)
            else:
                try:
                    await app.client.sign_in(
                        phone=phone, code=code, phone_code_hash=phone_hash)
                except SessionPasswordNeededError:
                    return "need_password"
            ensure_paths()
            SESSION_FILE.write_text(app.client.session.save(), encoding="utf-8")
            return "ok"

        def done(fut):
            self.login_btn.disabled = False
            try:
                r = fut.result()
                if r == "need_password":
                    self._show(self.pw)
                    self.msg.text = ar("الحساب محمي — أدخل كلمة المرور")
                else:
                    self.msg.text = ""
                    App.get_running_app().goto("main")
            except Exception as e:
                self.msg.text = ar("فشل الدخول: %s" % _err(e))

        WORKER.submit(task(), done)


# ---------------------------------------------------------------------------
# شاشة ٣ — التنزيل
# ---------------------------------------------------------------------------

MODES = {
    "القصص الحالية": "active",
    "المثبّتة على البروفايل": "pinned",
    "الكل": "all",
}


class MainScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.busy = False
        root = Pad(spacing=dp(10))

        root.add_widget(L("تنزيل القصص", 24, bold=True))
        root.add_widget(L("لا تُسجَّل مشاهدتك — الوضع مجهول دائمًا.",
                          13, (0.45, 0.85, 0.55, 1)))

        self.target = TI("@username")
        root.add_widget(self.target)

        # النص المعروض مُعاد تشكيله، فنحتفظ بخريطة عكسية بدل البحث بـ next()
        # الذي يرمي StopIteration ويُسقط التطبيق إن لم يطابق أي مفتاح.
        self._mode_by_label = {ar(k): v for k, v in MODES.items()}
        self.mode = Spinner(
            text=ar("الكل"),
            values=list(self._mode_by_label),
            size_hint_y=None, height=dp(46), font_size=dp(16),
            background_normal="", background_color=(0.15, 0.17, 0.22, 1),
        )
        root.add_widget(self.mode)

        self.go = BTN("ابدأ التنزيل", self.start)
        root.add_widget(self.go)

        sv = ScrollView()
        self.log_box = Label(
            text="", font_size=dp(13), halign="left", valign="top",
            size_hint_y=None, color=(0.80, 0.84, 0.90, 1),
        )
        self.log_box.bind(
            width=lambda w, v: setattr(w, "text_size", (v, None)),
            texture_size=lambda w, v: setattr(w, "height", v[1]),
        )
        sv.add_widget(self.log_box)
        root.add_widget(sv)

        self.path_lbl = L("", 11, MUTED, halign="left")
        root.add_widget(self.path_lbl)
        self.add_widget(root)

    # -- تسجيل آمن عبر الخيوط -------------------------------------------
    MAX_LOG_LINES = 300

    def log(self, msg):
        def _a(dt):
            lines = self.log_box.text.split("\n") if self.log_box.text else []
            lines.append(ar(str(msg)))
            # نص Label الضخم يتجاوز حدّ نسيج OpenGL ويُسقط العرض
            if len(lines) > self.MAX_LOG_LINES:
                lines = lines[-self.MAX_LOG_LINES:]
            self.log_box.text = "\n".join(lines) + "\n"
        Clock.schedule_once(_a, 0)

    def start(self, *_):
        if self.busy:
            return
        name = self.target.text.strip()
        if not name:
            self.log("أدخل اسم المستخدم أولًا")
            return
        if App.get_running_app().client is None:
            self.log("لا يوجد اتصال بتيليجرام")
            return

        mode = self._mode_by_label.get(self.mode.text, "all")

        self.busy = True
        self.go.disabled = True
        self.go.text = ar("جارٍ العمل ...")
        self.log_box.text = ""
        self.log(f"── {name}")

        def done(fut):
            self.busy = False
            self.go.disabled = False
            self.go.text = ar("ابدأ التنزيل")
            try:
                fut.result()
            except Exception as e:
                self.log(f"خطأ: {type(e).__name__}: {e}")

        WORKER.submit(self.download(name, mode), done)

    # -- المنطق الفعلي ---------------------------------------------------
    async def download(self, name, mode):
        from telethon import utils
        from telethon.errors import FloodWaitError
        from telethon.tl.functions.stories import (
            GetPeerStoriesRequest, GetPinnedStoriesRequest)
        from telethon.tl.types import StoryItem

        client = App.get_running_app().client

        try:
            entity = await client.get_entity(name)
            peer = await client.get_input_entity(entity)
        except Exception as e:
            self.log("تعذّر العثور على الحساب (%s)" % _err(e))
            return

        title = utils.get_display_name(entity) or "unknown"
        safe = "".join(c if c.isalnum() or c in "-_@." else "_" for c in title)
        safe = safe.strip("._") or ("id%s" % getattr(entity, "id", "unknown"))
        outdir = DOWNLOAD_DIR / safe
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log("تعذّر إنشاء المجلد (%s)" % _err(e))
            return

        stories, seen = [], set()

        if mode in ("active", "all"):
            try:
                r = await client(GetPeerStoriesRequest(peer=peer))
                got = [s for s in r.stories.stories if isinstance(s, StoryItem)]
                stories += got
                seen.update(s.id for s in got)
                self.log(f"نشطة: {len(got)}")
            except Exception as e:
                self.log("نشطة — تعذّر (%s)" % _err(e))

        if mode in ("pinned", "all"):
            try:
                offset, got = 0, []
                while True:
                    r = await client(GetPinnedStoriesRequest(
                        peer=peer, offset_id=offset, limit=50))
                    batch = [s for s in r.stories if isinstance(s, StoryItem)]
                    if not batch:
                        break
                    got += [s for s in batch if s.id not in seen]
                    seen.update(s.id for s in batch)
                    # الخادم قد يعيد نفس الدفعة؛ بلا هذا الشرط تدور الحلقة أبدًا
                    if batch[-1].id == offset:
                        break
                    offset = batch[-1].id
                    if len(batch) < 50:
                        break
                stories += got
                self.log(f"مثبّتة: {len(got)}")
            except Exception as e:
                self.log("مثبّتة — تعذّر (%s)" % _err(e))

        if not stories:
            self.log("لا توجد قصص متاحة")
            return

        stories.sort(key=lambda s: s.id)
        ok = fail = skip = 0
        for s in stories:
            if getattr(s, "noforwards", False):
                skip += 1
                self.log(f"#{s.id} محتوى محمي — تجاوز")
                continue
            if s.media is None:
                # قصة نصية فقط: لا يوجد ملف لتنزيله
                skip += 1
                self.log(f"#{s.id} بلا وسائط — تجاوز")
                continue

            try:
                ext = utils.get_extension(s.media) or ".bin"
            except Exception:
                ext = ".bin"
            stamp = s.date.strftime("%Y%m%d_%H%M%S") if s.date else "nodate"
            target = outdir / f"{stamp}_{s.id}{ext}"
            if target.exists() and target.stat().st_size > 0:
                skip += 1
                continue

            # FloodWait لا يعني فشل القصة، بل «انتظر ثم أعد المحاولة».
            # الكود القديم كان ينام ثم ينتقل للتالية فتضيع القصة بصمت.
            for attempt in range(3):
                try:
                    await client.download_media(s.media, file=str(target))
                    ok += 1
                    self.log(f"✓ {target.name}")
                    break
                except FloodWaitError as e:
                    wait = int(getattr(e, "seconds", 5)) + 2
                    self.log(f"انتظار {wait}s بسبب التقييد ...")
                    await asyncio.sleep(wait)
                except Exception as e:
                    fail += 1
                    self.log(f"✗ #{s.id} — {_err(e)}")
                    # ملف نصف منزَّل يُخدع فحص target.exists() لاحقًا
                    try:
                        if target.exists():
                            target.unlink()
                    except Exception:
                        pass
                    break
            else:
                fail += 1
                self.log(f"✗ #{s.id} — تعذّر بعد عدة محاولات")
            await asyncio.sleep(0.8)

        self.log(f"── تم {ok} | متجاوَز {skip} | فشل {fail}")
        self.log(f"المجلد: {outdir}")


# ---------------------------------------------------------------------------
# التطبيق
# ---------------------------------------------------------------------------

class LoadingScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        b = Pad()
        b.add_widget(Label())
        b.add_widget(L("جارٍ الاتصال ...", 20, halign="center"))
        b.add_widget(Label())
        self.add_widget(b)


class CrashScreen(Screen):
    """يعرض الخطأ على الشاشة بدل الانهيار الصامت — لا يوجد logcat على الهاتف."""

    def __init__(self, text, **kw):
        super().__init__(**kw)
        root = Pad(spacing=dp(8))
        root.add_widget(L("حدث خطأ أثناء الإقلاع", 20, (1, 0.5, 0.5, 1), bold=True))
        root.add_widget(L("صوّر هذي الشاشة وأرسلها.", 13, MUTED))
        sv = ScrollView()
        lbl = Label(text=text, font_size=dp(11), halign="left", valign="top",
                    size_hint_y=None, color=(1, 0.85, 0.85, 1))
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                 texture_size=lambda w, v: setattr(w, "height", v[1]))
        sv.add_widget(lbl)
        root.add_widget(sv)
        self.add_widget(root)


class TGStoriesApp(App):
    client = None
    _connecting = False

    def build(self):
        self.title = "TG Stories"
        Window.clearcolor = BG
        # يرفع الحقل فوق لوحة المفاتيح بدل أن تغطّيه
        Window.softinput_mode = "below_target"
        self.sm = ScreenManager(transition=SlideTransition(duration=0.2))
        try:
            self.sm.add_widget(LoadingScreen(name="loading"))
            self.sm.add_widget(SetupScreen(name="setup"))
            self.sm.add_widget(LoginScreen(name="login"))
            self.sm.add_widget(MainScreen(name="main"))
        except Exception:
            self.sm.add_widget(CrashScreen(traceback.format_exc(), name="crash"))
            self.sm.current = "crash"
            return self.sm
        Clock.schedule_once(lambda dt: self.safe_boot(), 0.4)
        return self.sm

    def crash(self, exc_text):
        try:
            if not self.sm.has_screen("crash"):
                self.sm.add_widget(CrashScreen(exc_text, name="crash"))
            self.sm.current = "crash"
        except Exception:
            traceback.print_exc()

    def goto(self, name):
        Clock.schedule_once(lambda dt: setattr(self.sm, "current", name), 0)

    def safe_boot(self):
        """كل ما يلمس أندرويد يُنفَّذ هنا، لا وقت الاستيراد."""
        try:
            _log("safe_boot: ensure_paths")
            ensure_paths()
            _log("safe_boot: paths ok -> %s" % DOWNLOAD_DIR)
            self.show_path()
            _log("safe_boot: boot_client")
            self.boot_client()
            # الأذونات تُطلب لاحقًا وبمعزل: android.permissions يمرّ عبر JNI،
            # ووضعها في مسار الإقلاع يعني أن فشلها يمنع التطبيق من العمل.
            # التخزين الخاص لا يحتاجها أصلًا.
            Clock.schedule_once(lambda dt: self.request_perms(), 2.0)
            _log("safe_boot: done")
        except Exception:
            _log("safe_boot FAILED")
            traceback.print_exc()
            self.crash(traceback.format_exc())

    def show_path(self):
        try:
            scr = self.sm.get_screen("main")
            scr.path_lbl.text = ar("الحفظ في: %s" % DOWNLOAD_DIR)
        except Exception:
            pass

    def request_perms(self):
        """
        بلا دالة رد نداء عمدًا.

        تمرير callback إلى request_permissions يسجّل مستمعًا على جانب Java
        ويستدعي بايثون من خيط أندرويد — وهو مسار JNI إضافي ينهار على بعض
        الأجهزة انهيارًا أصليًا لا يلتقطه try/except. نطلب الإذن ثم نستطلع
        النتيجة من خيط Kivy وحده.
        """
        if not ON_ANDROID:
            return
        _log("perms: requesting")
        try:
            from android.permissions import Permission, request_permissions
            request_permissions([Permission.WRITE_EXTERNAL_STORAGE,
                                 Permission.READ_EXTERNAL_STORAGE])
            _log("perms: requested")
        except Exception:
            _log("perms: unavailable (harmless)")
            return
        # المستخدم يحتاج وقتًا للرد على الحوار؛ نستطلع بدل انتظار رد نداء
        for delay in (3.0, 8.0, 15.0):
            Clock.schedule_once(lambda dt: self._after_perms(), delay)

    def _after_perms(self):
        """
        مجلد التنزيل اختير قبل منح الأذونات، فسقط دائمًا للمجلد الخاص.
        نعيد اختياره الآن بعد أن صارت /sdcard قابلة للكتابة.
        """
        try:
            if refresh_download_dir():
                _log("perms: downloads now at %s" % DOWNLOAD_DIR)
                self.show_path()
        except Exception:
            _log("perms: re-resolve failed")
            traceback.print_exc()

    def boot_client(self):
        if self._connecting:
            return
        cfg = load_config()
        if not cfg.get("api_id") or not cfg.get("api_hash"):
            self.goto("setup")
            return

        self._connecting = True
        self.goto("loading")

        async def connect():
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            # عميل قديم من محاولة سابقة يظل ممسكًا بالمقبس
            old, self.client = self.client, None
            if old is not None:
                try:
                    await old.disconnect()
                except Exception:
                    pass

            ensure_paths()
            saved = ""
            if SESSION_FILE.exists():
                try:
                    saved = SESSION_FILE.read_text(encoding="utf-8").strip()
                except Exception:
                    saved = ""
            try:
                session = StringSession(saved)
            except Exception:
                # جلسة تالفة تمنع الإقلاع للأبد — نبدأ من جديد
                _log("session: corrupt, discarding")
                try:
                    SESSION_FILE.unlink()
                except Exception:
                    pass
                session = StringSession()

            client = TelegramClient(
                session, cfg["api_id"], cfg["api_hash"],
                device_model="Android", system_version="13", app_version="1.0",
            )
            await client.connect()
            self.client = client
            return await client.is_user_authorized()

        def done(fut):
            self._connecting = False
            try:
                self.goto("main" if fut.result() else "login")
            except Exception as e:
                # بيانات API خاطئة أو لا شبكة: شاشة الانهيار طريق مسدود،
                # فنعيده للإعداد مع سبب الفشل بدل إجباره على إعادة التثبيت.
                _log("boot_client failed")
                traceback.print_exc()
                self.setup_error(_err(e))

        WORKER.submit(connect(), done)

    def setup_error(self, text):
        try:
            scr = self.sm.get_screen("setup")
            scr.msg.text = ar("تعذّر الاتصال — %s" % text)
            self.goto("setup")
        except Exception:
            self.crash(text)

    def on_stop(self):
        """يفصل العميل بهدوء حتى لا تبقى الجلسة معلّقة على الخادم."""
        client, self.client = self.client, None
        if client is None:
            return
        try:
            WORKER.run_sync(client.disconnect(), timeout=5)
            _log("client disconnected")
        except Exception:
            _log("client disconnect failed (harmless)")


if __name__ == "__main__":
    _log("step: starting app")
    try:
        TGStoriesApp().run()
    except Exception:
        _log("=== CRASH IN run() ===")
        traceback.print_exc()
        raise
