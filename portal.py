#!/usr/bin/env python3

import uuid
import dbus
from dbus.mainloop.glib import DBusGMainLoop

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
portal_obj = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
sc = dbus.Interface(portal_obj, "org.freedesktop.portal.ScreenCast")


def _wait_response(request_path):
    loop = GLib.MainLoop()
    out = {}

    def _on_response(code, results):
        out["code"] = int(code)
        out["results"] = {k: v for k, v in results.items()}
        loop.quit()

    bus.add_signal_receiver(
        _on_response,
        signal_name="Response",
        dbus_interface="org.freedesktop.portal.Request",
        path=request_path,
    )
    loop.run()
    return out.get("code", -1), out.get("results", {})


def create_session():
    token = uuid.uuid4().hex
    opts = {
        "session_handle_token": dbus.String(token),
        "handle_token": dbus.String(token),
        "types": dbus.UInt32(7),  # monitor+window+virtual
        "cursor_mode": dbus.UInt32(2),  # EMBED
    }
    req = sc.CreateSession(opts)
    code, res = _wait_response(req)
    if code or "session_handle" not in res:
        raise RuntimeError(f"CreateSession failed ({code}): {res}")
    return res["session_handle"]


def select_sources(sess):
    token = uuid.uuid4().hex
    opts = {
        "types": dbus.UInt32(1),  # screens only
        "multiple": dbus.Boolean(False),
        "cursor_mode": dbus.UInt32(2),
        "handle_token": dbus.String(token),
    }
    req = sc.SelectSources(sess, opts)
    code, _ = _wait_response(req)
    if code:
        raise RuntimeError(f"SelectSources failed ({code})")


def start_session(session_handle):
    token = uuid.uuid4().hex
    opts = {'handle_token': dbus.String(token)}
    request_path = sc.Start(session_handle, '', opts)
    code, res = _wait_response(request_path)
    if code != 0 or 'streams' not in res or not res['streams']:
        raise RuntimeError(f'Start failed ({code}): {res}')
    return res['streams'][0][0]

def close_session(sess):
    session_obj = bus.get_object("org.freedesktop.portal.Desktop", sess)
    session_iface = dbus.Interface(session_obj, "org.freedesktop.portal.Session")
    session_iface.Close()
    print(f"Session {sess} closed.")


