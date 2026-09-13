#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║              WINDOWS OPTIMIZER  v1.0                       ║
║        Systém-tweakek, debloat és cleanup Windows 10/11    ║
╚════════════════════════════════════════════════════════════╝

Futtatás:
    - dupla-klikk a windows-optimizer.pyw-ra (pythonw konzól nélkül fut)
    - vagy:  pythonw windows-optimizer.pyw

GUI nélkül (azonnal kilép, nem fut a háttérben):
    pythonw windows-optimizer.pyw --auto
        -> az alapbeállítás actionok futtávalva, a részletek a
           windows-optimizer-log.txt fájlban, aztán kilép
    pythonw windows-optimizer.pyw --help
        -> lehéli a használatot
"""

import os
import re
import sys
import shutil
import string
import threading
import subprocess
import platform
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# winreg csak Windows-on átkapható -> guard, hogy más rendszeren ne krasoljon
try:
    import winreg as _winreg
except ImportError:      # pragma: no cover
    _winreg = None

# Alias-k, hogy a Linux-on a tweak funkciók ne krasteoljanak a call időben
if _winreg is not None:
    HKEY_LOCAL_MACHINE = _winreg.HKEY_LOCAL_MACHINE
    HKEY_CURRENT_USER = _winreg.HKEY_CURRENT_USER
    REG_SZ = _winreg.REG_SZ
    REG_DWORD = _winreg.REG_DWORD
else:
    HKEY_LOCAL_MACHINE = None
    HKEY_CURRENT_USER = None
    REG_SZ = None
    REG_DWORD = None

IS_WINDOWS = (os.name == "nt")
IS_ADMIN = False
if IS_WINDOWS:
    try:
        IS_ADMIN = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        IS_ADMIN = False

APP_NAME = "Windows Optimizer"
APP_VERSION = "1.0"
PROBLEM = "\N{WARNING SIGN}"


# ────────────────────────────────────────────────────────────
#  Helper funkciók: registry, parancsok, PowerShell
# ────────────────────────────────────────────────────────────

def reg_set(root, key_path, name, value, reg_type):
    """Registry érték beállítás (kiszükséges ágakot automatikusan létrehoz)."""
    if _winreg is None:
        return False
    try:
        key = _winreg.CreateKeyEx(root, key_path, 0, _winreg.KEY_WRITE)
        try:
            _winreg.SetValueEx(key, name, 0, reg_type, value)
        finally:
            _winreg.CloseKey(key)
        return True
    except Exception:
        return False


def reg_get(root, key_path, name, default=None):
    """Registry érték lekódtás; ha nem létezik, retourne a default-ot."""
    if _winreg is None:
        return default
    try:
        key = _winreg.OpenKey(root, key_path)
        try:
            val, _ = _winreg.QueryValueEx(key, name)
            return val
        finally:
            _winreg.CloseKey(key)
    except Exception:
        return default


def _apply(*settings):
    """
    Több registry-beállítás egybe egyszerre.
    settings: (root, key_path, name, value, reg_type, label) tuple-ok.
    Retourne: (ok_bool, részlet-áhuzó)
    """
    if _winreg is None:
        return False, "Windows registry nem elérhető (nem Windows?)"
    parts = []
    ok_all = True
    for root, key_path, name, value, reg_type, label in settings:
        ok = reg_set(root, key_path, name, value, reg_type)
        ok_all = ok_all and ok
        parts.append(label + (u" \u2714" if ok else u" \u2716"))
    return ok_all, " | ".join(parts)


def run_cmd(cmd, timeout=120):
    """Egy parancs futtatása, kapturálva az outputot. Retourne: (ok, output)"""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, errors="replace")
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        combined = (out + ("\n" + err if err else "")).strip()
        return res.returncode == 0, combined
    except subprocess.TimeoutExpired:
        return False, "Timeout (" + str(timeout) + " mp)"
    except FileNotFoundError:
        return False, "Parancs nem talált: " + str(cmd[0])
    except Exception as e:
        return False, str(e)


def run_ps(script, timeout=300):
    """PowerShell egy-líner futtatása."""
    return run_cmd(["powershell", "-NoProfile", "-NonInteractive",
                    "-Command", script], timeout=timeout)


# ────────────────────────────────────────────────────────────
#  ACTION modell: ezeket a GUI checkbox-okkal mutat
# ────────────────────────────────────────────────────────────

class Action:
    def __init__(self, aid, name, desc, fn, admin=False, default=True):
        self.aid = aid
        self.name = name
        self.desc = desc
        self.fn = fn            # fn(log) -> (ok: bool, msg: str)
        self.admin = admin      # True: rendszeradmin jogosztság kell
        self.default = default  # alapbeállítással checkolt-e


# ────────────────────────────────────────────────────────────
#  TWEAK-ek  (rendszer-beállítás optimalizálás)
#  Kejek: Chris Titus WinUtil (config/tweaks.json) alapján
# ────────────────────────────────────────────────────────────

def tweak_startup_delay(log):
    """Kezdési hiba eltávolítása — a programok rábbidábban kezdődnek."""
    return _apply(
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer",
         "DisableCommonStartupDelay", 1, REG_DWORD,
         "DisableCommonStartupDelay=1"),
        (HKEY_CURRENT_USER, r"Control Panel\Desktop",
         "StartupDelayInMS", "0", REG_SZ,
         "StartupDelayInMS=0"),
    )


def tweak_fast_menu(log):
    """Gyors menü — menü-ábrassa delezé 0-ra."""
    return _apply(
        (HKEY_CURRENT_USER, r"Control Panel\Desktop",
         "MenuShowDelay", "0", REG_SZ, "MenuShowDelay=0"),
    )


def tweak_disable_animations(log):
    """Animációk leállítása — rugó, menü, ikon animációk."""
    return _apply(
        (HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics",
         "MinAnimate", "0", REG_SZ, "MinAnimate=0"),
        (HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "TaskbarAnimations", 0, REG_DWORD, "TaskbarAnimations=0"),
        (HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
         "VisualFXSetting", 3, REG_DWORD, "VisualFXSetting=3 (max teljesítmény)"),
        (HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM",
         "EnableAeroPeek", 0, REG_DWORD, "EnableAeroPeek=0"),
    )


def tweak_disable_telemetry(log):
    """Telemetria leállítása — Microsoft diagnosztikai adat-közlekedés."""
    return _apply(
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\DataCollection",
         "AllowTelemetry", 0, REG_DWORD, "AllowTelemetry=0"),
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Policies\Microsoft\Windows\System",
         "PublishUserActivities", 0, REG_DWORD, "PublishUserActivities=0"),
        (HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo",
         "Enabled", 0, REG_DWORD, "Ad-ID reklámköd=0"),
        (HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\Privacy",
         "TailoredExperiencesWithDiagnosticDataEnabled", 0, REG_DWORD,
         "TailoredExperiences=0"),
    )


def tweak_disable_hibernation(log):
    """Hibernáció leállítása — disk szabadtás."""
    ok_cmd, out = run_cmd(["powercfg", "/hibernate", "off"])
    ok_reg, det = _apply(
        (HKEY_LOCAL_MACHINE,
         r"System\CurrentControlSet\Control\Session Manager\Power",
         "HibernateEnabled", 0, REG_DWORD, "HibernateEnabled=0"),
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FlyoutMenuSettings",
         "ShowHibernateOption", 0, REG_DWORD, "ShowHibernateOption=0"),
    )
    return ok_cmd and ok_reg, "powercfg: " + ("OK" if ok_cmd else out) + " | " + det


def tweak_power_plan(log):
    """Magas teljesítmény power plan aktiválása."""
    ok, out = run_cmd(["powercfg", "/list"])
    if not ok:
        return False, "powercfg /list hibás: " + out
    guid = None
    for line in out.splitlines():
        low = line.lower()
        if any(k in low for k in ("high performance", "magas teljesítmény",
                                  "höchste leistung", "alto rendimiento",
                                  "prestazioni", "haute performance")):
            m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", line)
            if m:
                guid = m.group(1)
                break
    if not guid:
        return False, "High performance plan nem talált a powercfg /list-ben"
    ok2, out2 = run_cmd(["powercfg", "/setactive", guid])
    if ok2:
        return True, "Power plan aktiv: " + guid
    return False, out2

def tweak_no_sleep(log):
    """Standby/sleep időutok leállítása (AC mellett, desktop)."""
    parts = []
    ok_all = True
    for arg in (["standby-timeout-ac"], ["hibernate-timeout-ac"], ["disk-timeout-ac"]):
        ok, out = run_cmd(["powercfg", "/change", arg[0], "0"])
        ok_all = ok_all and ok
        parts.append(arg[0] + (u" \u2714" if ok else u" \u2716"))
    return ok_all, " | ".join(parts)


def tweak_disable_p2p_updates(log):
    """Windows Update P2P fogyászti letöltés leállítása."""
    return _apply(
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization",
         "DODownloadMode", 0, REG_DWORD, "DODownloadMode=0"),
    )


def tweak_disable_cortana(log):
    """Cortana / hang-asszisztent leállítása."""
    return _apply(
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Policies\Microsoft\Windows\Windows Search",
         "AllowCortana", 0, REG_DWORD, "AllowCortana=0"),
    )


def tweak_disable_consumer_features(log):
    """Reklámok és sugesztiók (Cloud Content) leállítása."""
    return _apply(
        (HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Policies\Microsoft\Windows\CloudContent",
         "DisableWindowsConsumerFeatures", 1, REG_DWORD,
         "DisableWindowsConsumerFeatures=1"),
    )


def tweak_disable_bg_apps(log):
    """Háttóérben futó app-ok leállítása (Win11)."""
    return _apply(
        (HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
         "GlobalUserDisabled", 1, REG_DWORD, "GlobalUserDisabled=1"),
    )


def tweak_disable_telemetry_services(log):
    """Telemetria szervízek leállítása (diagtrack)."""
    parts = []
    ok_all = True
    for svc in ("diagtrack",):
        ok, _ = run_cmd(["sc", "config", svc, "start", "disabled"])
        run_cmd(["sc", "stop", svc])
        parts.append(svc + (u" \u2714" if ok else u" \u2716 (nem létezik?)"))
        ok_all = ok_all and ok
    return ok_all, " | ".join(parts)


TWEAKS = [
    Action("startup_delay", "Kezdési hiba eltávolítás",
           "A Windows 10 mp-os kezdési hiba eltávolítása — a rendszer és a programok "
           "gyorsabban kezdődnek", tweak_startup_delay, admin=True),
    Action("fast_menu", "Gyors menü",
           "A menü-ábrassa delezé 0 mp-ra — limitábban nyílnak a menük",
           tweak_fast_menu),
    Action("animations", "Animációk leállítás",
           "Rugó, menü, ikon és Aero-ábrassél animációk leállítása — "
           "smábban érződik a rendszer", tweak_disable_animations),
    Action("telemetry", "Telemetria leállítás",
           "Microsoft diagnosztikai adat-közlekedés, Ad-ID és telemetria leállítása "
           "(privacy + keveseb net-fogyásztas)", tweak_disable_telemetry, admin=True),
    Action("hibernation", "Hibernáció leállítás",
           "Hibernáció fájl eltávolítása — disk szabadtás (laptop-on nem feltétlen!)",
           tweak_disable_hibernation, admin=True),
    Action("power_plan", "Magas teljesítmény power plan",
           "A leggyorsabb power plan aktiválása (CPU/GPU max frekventi)",
           tweak_power_plan, admin=True),
    Action("no_sleep", "Sleep/standby leállítás",
           "A PC nem menne sleep-be és a disk nem áll le AC mellett (desktop)",
           tweak_no_sleep, admin=True),
    Action("p2p_update", "Windows Update P2P leállítás",
           "A fogyászti letöltés (P2P / Delivery Optimization) leállítása",
           tweak_disable_p2p_updates, admin=True),
    Action("cortana", "Cortana leállítás",
           "Cortana / Windows Search hang-asszisztent leállítása",
           tweak_disable_cortana, admin=True),
    Action("consumer", "Reklámok leállítás",
           "Windows-béltű csúnya reklámok és sugesztiók (Cloud Content) eltávolítása",
           tweak_disable_consumer_features, admin=True),
    Action("bg_apps", "Háttóér app-ok leállítás",
           "A háttóérben futó app-ok megállítása (Windows 11)",
           tweak_disable_bg_apps),
    Action("telemetry_svc", "Telemetria szervíze leállítás",
           "diagtrack szervíz leállítása (rendszer-jog algoritm)",
           tweak_disable_telemetry_services, admin=True),
]

# ────────────────────────────────────────────────────────────
#  DEBLOAT — bloatware eltávolítás
#  A PackageId-k: Chris Titus WinUtil (config/appx.json)
# ────────────────────────────────────────────────────────────

BLOAT_PATTERNS = [
    # --- Microsoft hiatus: nem használt appok ---
    "Microsoft.WindowsFeedbackHub",      # Feedback Hub
    "Microsoft.GetHelp",                 # Get Help
    "Microsoft.OutlookForWindows",       # New Outlook
    "MSTeams",                           # Microsoft Teams
    "Clipchamp.Clipchamp",               # Clipchamp videóedtor
    "Microsoft.MicrosoftOfficeHub",      # Office Home & trial
    "Microsoft.ZuneMusic",               # Zune Music app
    "Microsoft.ZuneVideo",               # Zune Video app
    "Microsoft.BingNews",                # Bing hírek
    "Microsoft.BingWeather",             # Bing vére
    "Microsoft.BingSearch",              # Bing kereső
    "MicrosoftCorporationII.QuickAssist",# Quick Assist
    "Microsoft.Windows.DevHome",         # Dev Home
    "MicrosoftWindows.CrossDevice",      # Cross Device mystic
    "Microsoft.Todos",                   # Microsoft To Do
    "Microsoft.PowerAutomateDesktop",    # Power Automate
    "Microsoft.YourPhone",               # Your Phone
    "Microsoft.WindowsSoundRecorder",    # Sound Recorder
    "Microsoft.WindowsAlarms",           # Alarms & Clock
    "Microsoft.MicrosoftSolitaireCollection",  # Solitaire
    "Microsoft.GamingApp",               # Xbox Gaming App
    "Microsoft.Xbox",                    # Xbox komponensek
    "Microsoft.Copilot",                 # Copilot (Win11)
    # --- OEM / harmad party bloat (gyárakis appok) ---
    "king.com.CandyCrush",               # Candy Crush Saga
    "McAfee", "Norton", "AVG", "Avast",  # antic-vírus reklám
    "Dropbox", "Evernote",               # OEM appok
    "Facebook", "Messenger",
    "Spotify", "Tiktok", "Zoom", "Skype",
    "Disney", "Duolingo", "Pinterest",
    "booking.com", "Hilton", "Expedia", "Tripadvisor",
    "Yandex", "mail.ru",
]


def debloat_store_apps(log):
    """A BLOAT_PATTERNS minta alapján eltávolítja a Microsoft Store appok."""
    if not IS_WINDOWS:
        return False, "Csak Windows-on fut"
    pats = ", ".join('"%s"' % p for p in BLOAT_PATTERNS)
    script = (
        "$pats = @( %s )\n"
        "foreach ($pat in $pats) {\n"
        "  try { $apps = @(Get-AppxPackage -AllUsers | Where-Object "
        "{ $_.Name -like ('*' + $pat + '*') }) } catch { $apps = @() }\n"
        "  $f = $apps.Count\n"
        "  foreach ($app in $apps) {\n"
        "    try { Remove-AppxPackage -Package $app.PackageFullName "
        "-AllUsers -ErrorAction SilentlyContinue } catch {}\n"
        "  }\n"
        "  try { $left = @(Get-AppxPackage -AllUsers | Where-Object "
        "{ $_.Name -like ('*' + $pat + '*') }) } catch { $left = @() }\n"
        "  Write-Output ($pat + '|' + $f + '|' + $left.Count)\n"
        "}\n"
    ) % pats
    ok, out = run_ps(script, timeout=420)
    found_total = removed_total = 0
    if ok and out:
        for line in out.splitlines():
            m = re.match(r"^(.+)\|(\d+)\|(\d+)$", line.strip())
            if not m:
                continue
            pat, f, l = m.group(1), int(m.group(2)), int(m.group(3))
            if f == 0:
                continue
            found_total += f
            removed_total += (f - l)
            if l:
                log(u"   %s: %d talált, %d maradt (locked / nem eltávolítás)" % (pat, f, l))
            else:
                log(u"   eltávolított: %s (%d)" % (pat, f))
    if ok and found_total == 0:
        return True, "Nem volt mast bloatware a rendszeren"
    if ok:
        return True, "Össze: %d app talált, %d eltávolított" % (found_total, removed_total)
    return False, out or "PowerShell hiba"


DEBLOATS = [
    Action("store_bloat", "Microsoft Store bloatware eltávolítás",
           "Candy Crush, Teams, New Outlook, Bing-junk, Xbox Gaming App, Spotify, "
           "TikTok, Norton/McAfee stb. (BLOAT_PATTERNS lista). A removed appok "
           "később a Store-ból újraintallálhatók.",
           debloat_store_apps, admin=True),
]

# ────────────────────────────────────────────────────────────
#  CLEANUP — disk szabadtás és junk eltávolítás
# ────────────────────────────────────────────────────────────

def _wipe_folder(path_str, log):
    """A mappa tartalmazás eltávolítása; locked fájlok skippelés."""
    p = Path(path_str)
    if not p.exists():
        return 0, True
    deleted = 0
    try:
        entries = list(p.iterdir())
    except Exception:
        return 0, False
    for child in entries:
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
            deleted += 1
        except Exception:
            pass
    return deleted, True


def cleanup_temp(log):
    """Temp mappák (user + rendszer) szabadtás."""
    targets = set()
    for var in ("TEMP", "TMP"):
        t = os.environ.get(var)
        if t:
            targets.add(t)
    windir = os.environ.get("WINDIR", "C:\\Windows")
    targets.add(os.path.join(windir, "Temp"))
    total = 0
    for t in targets:
        n, _ = _wipe_folder(t, log)
        total += n
    return True, "temp-mappákból eltávolított: %d elem" % total


def cleanup_recycle(log):
    """Recycle bin szabádás."""
    ok, out = run_ps("Clear-RecycleBin -Force -ErrorAction SilentlyContinue; 'ok'", 120)
    if ok:
        return True, "Recycle bin szabad"
    total = 0
    for drive in string.ascii_uppercase:
        p = Path("%s:\\$Recycle.Bin" % drive)
        if p.exists():
            n, _ = _wipe_folder(str(p), log)
            total += n
    return True, "Recycle bin szabad (fallback, %d elem)" % total


def cleanup_dns(log):
    """DNS cache szabádás."""
    ok, out = run_cmd(["ipconfig", "/flushdns"], timeout=60)
    if ok:
        return True, "DNS cache szabad"
    return False, out or "ipconfig hiba"


def cleanup_update_cache(log):
    """Windows Update letöltés cache szabádás."""
    windir = os.environ.get("WINDIR", "C:\\Windows")
    n, _ = _wipe_folder(os.path.join(windir, "SoftwareDistribution", "Download"), log)
    return True, "Update cache elemei: %d" % n


def cleanup_thumbnails(log):
    """Ikon- és thumbnail cache szabádás."""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(str(Path.home()),
                                                           "AppData", "Local")
    expl = Path(local) / "Microsoft" / "Windows" / "Explorer"
    deleted = 0
    if expl.exists():
        for f in expl.iterdir():
            try:
                if f.is_file() and (f.name.startswith("thumbcache") or
                                    f.name.startswith("iconcache")):
                    f.unlink()
                    deleted += 1
            except Exception:
                pass
    return True, "Cache fájlok: %d" % deleted


def cleanup_minidump(log):
    """Crash dump (Minidump) eltávolítás."""
    windir = os.environ.get("WINDIR", "C:\\Windows")
    n, _ = _wipe_folder(os.path.join(windir, "Minidump"), log)
    return True, "Minidump fájlok: %d" % n


def cleanup_prefetch(log):
    """Prefetch cache szabádás (a kezdés smástrias, de szabadtja disk-et)."""
    windir = os.environ.get("WINDIR", "C:\\Windows")
    p = Path(windir) / "Prefetch"
    deleted = 0
    if p.exists():
        for f in p.glob("*.pf"):
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
    return True, "Prefetch fájlok: %d" % deleted


def cleanup_windows_old(log):
    """Windows.old eltávolítása (a régi rendszer backup, GB-os szabadtás)."""
    sysdrv = os.environ.get("SystemDrive", "C:")
    old = Path(sysdrv) / "Windows.old"
    if not old.exists():
        return True, "Windows.old nem létezik (nem volt updgrade)"
    ok, out = run_ps("Remove-Item -Path '%s' -Recurse -Force -ErrorAction SilentlyContinue; if (Test-Path '%s') { 'LEFT' } else { 'GONE' }" % (old, old), timeout=900)
    return ok and "LEFT" not in out, "Windows.old: " + (out or "eltávolítás")


CLEANUPS = [
    Action("cleanup_temp", "Temp fájlok",
           "%TEMP%, %TMP% és C:\\Windows\\Temp szabádás — GB-os szabadtás",
           cleanup_temp, admin=True),
    Action("cleanup_recycle", "Recycle bin",
           "A Törölözésszél mappa szabádás",
           cleanup_recycle),
    Action("cleanup_thumbnails", "Ikon/thumbnail cache",
           "A Explorer cache eltávolítása (ikon- és thumbnail mappák)",
           cleanup_thumbnails),
    Action("cleanup_dns", "DNS cache",
           "ipconfig /flushdns — a DNS cache szabádás",
           cleanup_dns),
    Action("cleanup_update", "Windows Update cache",
           "A letöltött update-fájlok szabádás (SoftwareDistribution\\Download)",
           cleanup_update_cache, admin=True),
    Action("cleanup_minidump", "Crash dump-ok",
           "C:\\Windows\\Minidump szabádás (BSOD dumo)", cleanup_minidump,
           admin=True, default=False),
    Action("cleanup_prefetch", "Prefetch cache",
           "C:\\Windows\\Prefetch szabádás — disk szabadtás, de a kezdés "
           "smástrias lehet később", cleanup_prefetch, admin=True, default=False),
    Action("cleanup_old", "Windows.old eltávolítás",
           "A régi rendszer backup eltávolítása (10-20+ GB szabadtás)",
           cleanup_windows_old, admin=True, default=False),
]

# ────────────────────────────────────────────────────────────
#  RENDSZERINFO — Info tab tartalma
# ────────────────────────────────────────────────────────────

def get_ram_info():
    """Megad total/available RAM GlobalMemoryStatusEx API-val."""
    if not IS_WINDOWS:
        return None
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("dwTotalPhys", ctypes.c_ulonglong),
                ("dwAvailPhys", ctypes.c_ulonglong),
                ("dwTotalPageFile", ctypes.c_ulonglong),
                ("dwAvailPageFile", ctypes.c_ulonglong),
                ("dwTotalVirtual", ctypes.c_ulonglong),
                ("dwAvailVirtual", ctypes.c_ulonglong),
                ("dwAvailSystemCache", ctypes.c_ulonglong),
                ("dwTotalSwap", ctypes.c_ulonglong),
                ("dwAvailSwap", ctypes.c_ulonglong),
            ]
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return mem.dwTotalPhys, mem.dwAvailPhys
    except Exception:
        pass
    return None


def fmt_size(n):
    """Bytes -> emberzött string."""
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return str(n)


def collect_system_info():
    """Info tab adat-kollektál. Retourne: sort listes (label, value)."""
    rows = []
    try:
        rows.append(("Windows", platform.system() + " " + platform.release()))
    except Exception:
        pass
    try:
        wv = sys.getwindowsversion()
        rows.append(("Windows build", "%d.%d.%d (build %d)" % (wv[0], wv[1], wv[2], wv[3])))
    except Exception:
        pass
    rows.append(("CPU", platform.processor() or "-"))
    try:
        rows.append(("CPU cores", str(os.cpu_count())))
    except Exception:
        pass
    r = get_ram_info()
    if r:
        total, avail = r
        rows.append(("RAM", "%s össze / %s szabad" % (fmt_size(total), fmt_size(avail))))
    try:
        du = shutil.disk_usage("C:\\")
        rows.append(("C: disk", "%s össze / %s szabad / %s használt" %
                     (fmt_size(du.total), fmt_size(du.free), fmt_size(du.used))))
    except Exception:
        pass
    try:
        ok, out = run_ps("(Get-Date) - (Get-CimInstance -ClassName CIM_OperatingSystem).LastBootUpTime | Select-Object -First 1 | ForEach-Object { [math]::Round($_.TotalMinutes / 60, 1) }", 60)
        if ok and out.strip():
            rows.append(("Uptime", out.strip() + " óra"))
    except Exception:
        pass
    rows.append(("Kezdött: ", ("admin (rendszeradmin)" if IS_ADMIN else "normál user")))
    rows.append(("Platform", platform.platform() + (" (64-bit)" if sys.maxsize > 2**32 else " (32-bit)")))
    rows.append(("Python", sys.version.split()[0]))
    rows.append(("Script", os.path.abspath(sys.argv[0])))
    return rows


# ────────────────────────────────────────────────────────────
#  GUI — tkinter
# ────────────────────────────────────────────────────────────

import queue as _queue


class OptimizerApp:
    def __init__(self, root):
        self.root = root
        root.title("%s v%s" % (APP_NAME, APP_VERSION))
        root.geometry("880x700")
        root.minsize(800, 620)
        self.log_q = _queue.Queue()
        self.running = False
        self.stop_flag = False
        self._wheel_canvas = None
        self.root.bind_all("<MouseWheel>", self._on_wheel)

        self._build_header()
        self._build_notebook()
        self._build_buttons()
        self._build_log()
        self._build_statusbar()
        self.root.after(120, self._drain_log)

    # ── header ─────────────────────────────────────────────
    def _build_header(self):
        top = tk.Frame(self.root, bg="#20242e")
        top.pack(fill="x")
        tk.Label(top, text=u"\u26a1  " + APP_NAME,
                 font=("Segoe UI", 15, "bold"),
                 fg="#ffffff", bg="#20242e").pack(side="left", padx=14)
        right = tk.Frame(top, bg="#20242e")
        right.pack(side="right", padx=8)
        if not IS_WINDOWS:
            tk.Label(right, text=PROBLEM + " Ez a script WINDOWS-ra fut!",
                     fg="#ff6b6b", bg="#20242e",
                     font=("Segoe UI", 10, "bold")).pack(side="right")
        elif not IS_ADMIN:
            tk.Label(right, text=PROBLEM + " Háte: rendszeradmin jogot kell",
                     fg="#ffd166", bg="#20242e",
                     font=("Segoe UI", 10, "bold")).pack(side="right")
        tk.Label(top, text="Tweakek · Debloat · Cleanup · Win10/11",
                 fg="#9fd0ff", bg="#20242e",
                 font=("Segoe UI", 9)).pack(side="right", padx=(0, 8))

    # ── notebook / tabok ────────────────────────────────────
    def _build_notebook(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(4, 2))
        self.tabs = {}
        self.var_map = {}
        self._action_tab("tweaks", "  Tweakek  ", TWEAKS)
        self._action_tab("debloat", "  Debloat  ", DEBLOATS)
        self._action_tab("cleanup", "  Cleanup  ", CLEANUPS)
        self._info_tab()

    def _action_tab(self, key, title, actions):
        frame = tk.Frame(self.nb)
        self.nb.add(frame, text=title)
        canvas = tk.Canvas(frame, highlightthickness=0)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda e: setattr(self, "_wheel_canvas", canvas))
        canvas.bind("<Leave>", lambda e: setattr(self, "_wheel_canvas", None))

        for act in actions:
            var = tk.BooleanVar(value=act.default)
            self.var_map[act.aid] = var
            self.tabs.setdefault(key, []).append((act, var))
            card = tk.Frame(inner, bg="#f4f6f9",
                            highlightbackground="#d5dbe3", highlightthickness=1)
            card.pack(fill="x", padx=6, pady=(4, 2))
            row = tk.Frame(card, bg="#f4f6f9")
            row.pack(fill="x")
            tk.Checkbutton(row, variable=var, bg="#f4f6f9",
                           activebackground="#f4f6f9",
                           highlightthickness=0).pack(side="left")
            name = act.name
            badge = False
            if act.admin:
                name += "  " + (u"\u26a0 RENDSZERADMIN" if not IS_ADMIN else u"\u26a0 admin")
                badge = True
            tk.Label(row, text=name, font=("Segoe UI", 11, "bold"),
                     bg="#f4f6f9",
                     fg="#e8873a" if badge else "#1f2833").pack(side="left",
                                                                padx=(2, 4))
            tk.Label(card, text=act.desc, wraplength=740, justify="left",
                     font=("Segoe UI", 9), fg="#5a6472",
                     bg="#f4f6f9").pack(fill="x", padx=30, pady=(0, 2))

    def _on_wheel(self, e):
        c = self._wheel_canvas
        if c is not None:
            c.yview_scroll(int(-e.delta / 120), "units")

    # ── Info tab ────────────────────────────────────────────
    def _info_tab(self):
        frame = tk.Frame(self.nb)
        self.nb.add(frame, text="  Info  ")
        txt = tk.Text(frame, font=("Consolas", 10), wrap="word",
                      bg="#f4f6f9", fg="#22303c")
        sb = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        sb.pack(side="right", fill="y")
        txt.insert("end", "RENDSZERINFO\n" + "=" * 42 + "\n\n")
        for label, value in collect_system_info():
            txt.insert("end", "%-18s: %s\n" % (label, value))
        txt.insert("end", "\n\n" + "=" * 42 + "\n")
        txt.insert("end",
                   "Használat:\n"
                   "  1. Választ a tickekkel a tweak/debloat/cleanup actionok\n"
                   "  2. Klikk a 'Futtat a selectált'\n"
                   "  3. A log-ban követ a részleteket\n\n"
                   "Megjegyzés:\n"
                   "  - Az admin-actionok rendszeradmin jogot igényelnek.\n"
                   "  - A store-appok a debloat után a Microsoft Store-ból\n"
                   "    újraintallálhatók.\n"
                   "  - Kéked, mielőtt futtatod — saját felelősség azaz!")

# ── nappok-buttons ──────────────────────────────────────
    def _build_buttons(self):
        bar = tk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(2, 2))
        self.run_btn = tk.Button(
            bar, text=u"\u25b6  Futtat a selectált", command=self.run_selected,
            font=("Segoe UI", 11, "bold"), bg="#2f9e5f", fg="#ffffff",
            activebackground="#37b06b", padx=16, pady=4, cursor="hand2")
        self.run_btn.pack(side="left")
        tk.Button(bar, text="Mindegyik",
                  command=lambda: self.select_all(True)).pack(side="left", padx=6)
        tk.Button(bar, text="Töröl",
                  command=lambda: self.select_all(False)).pack(side="left", padx=6)
        tk.Button(bar, text="Alapbeállítás",
                  command=self.reset_defaults).pack(side="left", padx=6)
        if not IS_ADMIN and IS_WINDOWS:
            tk.Button(bar, text=u"\u21fb  Kezdés adminként",
                      command=self.relaunch_admin, bg="#e8a33d",
                      fg="#111111").pack(side="left", padx=6)
        # Auto-close: a futás utáni automatikusan kiválja a GUI-t,
        # hogy ne fusson a háttérben a útjáig
        self.auto_close = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Kivész a futás utáni",
                       variable=self.auto_close).pack(side="right", padx=6)

    # ── log-panel ───────────────────────────────────────────
    def _build_log(self):
        wrap = tk.Frame(self.root)
        wrap.pack(fill="both", expand=True, padx=8, pady=(2, 2))
        self.log = tk.Text(wrap, height=11, font=("Consolas", 9),
                           state="disabled", bg="#1c1e26", fg="#cfd6e4",
                           wrap="word")
        sb = ttk.Scrollbar(wrap, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, color in (("info", "#5dade2"), ("ok", "#2ecc71"),
                           ("fail", "#e74c3c"), ("head", "#9fd0ff")):
            self.log.tag_configure(tag, foreground=color)
        self._append_log(
            u"\u27ea %s v%s — válaszd actionok és klikk 'Futtat' \u27eb"
            % (APP_NAME, APP_VERSION), "head")

    def _build_statusbar(self):
        self.status = tk.Label(self.root, text="Résztelel", anchor="w",
                               relief="sunken", font=("Segoe UI", 9))
        self.status.pack(fill="x", side="bottom")

# ── select/run logika ─────────────────────────────────────
    def all_actions(self):
        items = []
        for acts in self.tabs.values():
            items.extend(acts)
        return items

    def select_all(self, val):
        for act, var in self.all_actions():
            var.set(val)

    def reset_defaults(self):
        for act, var in self.all_actions():
            var.set(act.default)

    def run_selected(self):
        if self.running:
            return
        if not IS_WINDOWS:
            messagebox.showerror(APP_NAME,
                                 "Ez a script Windows-on fut!\n(.pyw -> pythonw)")
            return
        selected = [act for act, var in self.all_actions() if var.get()]
        if not selected:
            messagebox.showinfo(APP_NAME, "Kérlek választ legalább egy actiont!")
            return
        self.running = True
        self.run_btn.configure(state="disabled", text=u"\u23f3  Fut a ...")
        self.status.configure(text="Fut a ...")
        threading.Thread(target=self._worker, args=(selected,),
                         daemon=True).start()

    def _worker(self, actions):
        for idx, act in enumerate(actions, 1):
            self.push(u"\u25b6 [%d/%d] %s ..." % (idx, len(actions), act.name),
                      "info")
            if act.admin and not IS_ADMIN:
                self.push(
                    u"    \u2716 Rendszeradmin jogot kell! Használd a "
                    u"'Kezdés adminként' opciót", "fail")
                continue
            try:
                ok, msg = act.fn(self.push)
            except Exception as e:
                ok, msg = False, "Részele: %r" % (e,)
            if ok:
                self.push(u"    \u2714  " + msg, "ok")
            else:
                self.push(u"    \u2716  " + msg, "fail")
        self.push("──── Össze. ────", "head")
        self.push(None, "done")

    def push(self, text, kind="info"):
        self.log_q.put((kind, text))

    def _drain_log(self):
        try:
            while True:
                kind, text = self.log_q.get_nowait()
                if kind == "done":
                    self.running = False
                    self.run_btn.configure(state="normal",
                                           text=u"\u25b6  Futtat a selectált")
                    self.status.configure(text="Kész.")
                    if self.auto_close.get():
                        self.root.after(600, self.root.destroy)
                    continue
                self._append_log(text, kind)
        except _queue.Empty:
            pass
        # Háttóér-poling: busy mellett gyors (120 ms), idle mellett lanyú (2.5 s),
        # hogy a GUI ne fusson le a háttérben, ha nem fut épp mit
        delay = 120 if self.running else 2500
        self.root.after(delay, self._drain_log)

    def _append_log(self, text, kind="info"):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", kind)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ── admin-newstart ───────────────────────────────────────
    def relaunch_admin(self):
        if not IS_WINDOWS:
            return
        script = os.path.abspath(sys.argv[0])
        exe = sys.executable
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe,
                                                 '"%s"' % script, None, 1)
        if rc == 0:
            messagebox.showerror(APP_NAME, "A admin-kézdeolog nélüg eltudott =(")
        else:
            messagebox.showinfo(
                APP_NAME,
                "A új mémó rendszeradmin jogokkal futattva.\n"
                "Várj pár mp-t, aztán ezt a mémó választ!")


# ────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────

def run_headless(actions, log):
    """GUI nélkül futtatja a actionok és a log-ot egy fájlba írja. Ösz kilép."""
    log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                            "windows-optimizer-log.txt")
    lines = []
    def sink(msg, kind="info"):
        lines.append(str(msg))
    for idx, act in enumerate(actions, 1):
        lines.append("=" * 46)
        lines.append(u"[%d/%d] %s" % (idx, len(actions), act.name))
        if act.admin and not IS_ADMIN:
            lines.append(u"   \u2716 SKIP -> rendszeradmin jogot kell! (%s)" % act.aid)
            continue
        try:
            ok, msg = act.fn(sink)
        except Exception as e:
            ok, msg = False, "Részele: %r" % (e,)
        lines.append(u"   %s  %s" % (u"\u2714" if ok else u"\u2716", msg))
    lines.append("=" * 46)
    lines.append("Össze. Log-fájl: %s" % log_path)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass
    log(log_path if log else None)
    return log_path


def _out(s=""):
    """Konzól-safe print (pythonw-nál a stdout None lehet)."""
    try:
        print(s)
    except Exception:
        pass


def main():
    if not IS_WINDOWS:
        _out("Ez a script Windows-on fut!")
        return
    root = tk.Tk()
    try:
        if sys.platform == "win32":
            root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    OptimizerApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    if "--auto" in args or "-a" in args or "--silent" in args or "-s" in args:
        # SILD CLI: GUI nélkül futtatás, azonnal kilép — nem fusson a háttérben
        actions = [a for a in (TWEAKS + DEBLOATS + CLEANUPS) if a.default]
        run_headless(actions, _out)
        sys.exit(0)
    if "--help" in args or "-h" in args:
        try:
            _out(__doc__)
        except Exception:
            pass
        _out("Opciók:")
        _out("  --auto / -a / --silent / -s")
        _out("      GUI nélkül futtatja az alapbeállítás actionok és kilép;\n"
             "      a részletek: windows-optimizer-log.txt")
        _out("  --help / -h   ez a segítsége")
        sys.exit(0)
    main()