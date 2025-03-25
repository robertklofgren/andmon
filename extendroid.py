#!/usr/bin/env python3
import sys
import os
import time
import uuid
import subprocess
import json
import gi

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gio, GLib, Gst, GstRtspServer, GObject

def pause_debug(msg="Pausing for debugging... Press Ctrl-C to exit."):
    print(msg)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting debug pause.")

def check_vkms():
    try:
        with open("/proc/modules", "r") as f:
            data = f.read()
            print("Current /proc/modules content:", data.strip())
            if "vkms" not in data:
                print("vkms not found in modules; loading vkms...")
                subprocess.run(["sudo", "modprobe", "vkms"], check=True)
            else:
                print("vkms already loaded.")
    except Exception as e:
        print(f"VKMS error: {e}")
        pause_debug("VKMS error encountered. Pausing for debugging.")

def create_dbus_proxy():
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        print("Obtained D-Bus session connection:", connection)
        proxy = Gio.DBusProxy.new_sync(
            connection,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.ScreenCast",
            None
        )
        print("Created D-Bus proxy for ScreenCast:", proxy)
        return proxy, connection
    except Exception as e:
        print(f"DBus error: {e}")
        pause_debug("DBus error encountered. Pausing for debugging.")
        return None, None

def wait_for_response(connection, request_path, timeout=10):
    print(f"Waiting for response on request path: {request_path} with timeout {timeout}s")
    response = {}
    loop = GLib.MainLoop()

    def handler(_conn, _sender, path, _iface, _signal, params):
        print(f"Signal received for path: {path} with params: {params}")
        if path == request_path:
            response.update({"code": params[0], "results": params[1] or {}})
            print("Response captured:", response)
            loop.quit()

    sub = connection.signal_subscribe(
        None, "org.freedesktop.portal.Request", "Response",
        request_path, None, Gio.DBusSignalFlags.NO_MATCH_RULE, handler
    )
    GLib.timeout_add_seconds(timeout, loop.quit)
    loop.run()
    connection.signal_unsubscribe(sub)
    print(f"Final response for {request_path}: {response}")
    return response

def create_session(proxy, connection):
    try:
        options = {
            "session_handle_token": GLib.Variant("s", uuid.uuid4().hex),
            "handle_token": GLib.Variant("s", uuid.uuid4().hex)
        }
        print("Creating session with options:", options)
        result = proxy.call_sync(
            "CreateSession",
            GLib.Variant("(a{sv})", (options,)),
            Gio.DBusCallFlags.NONE, -1, None
        )
        request_path = result.unpack()[0]
        print("CreateSession request path:", request_path)
        response = wait_for_response(connection, request_path)
        print("CreateSession response:", response)
        session_handle = response["results"].get("session_handle")
        if not session_handle:
            print("Session handle not received.")
            pause_debug("No session handle. Pausing for debugging.")
        else:
            print("Obtained session handle:", session_handle)
        return session_handle
    except Exception as e:
        print(f"CreateSession failed: {e}")
        pause_debug("CreateSession failed. Pausing for debugging.")
        return None

def select_sources(proxy, connection, session_handle):
    try:
        options = {
            "types": GLib.Variant("u", 1),
            "cursor_mode": GLib.Variant("u", 2),
            "handle_token": GLib.Variant("s", uuid.uuid4().hex)
        }
        print("Selecting sources with session_handle:", session_handle)
        print("SelectSources options:", options)
        result = proxy.call_sync(
            "SelectSources",
            GLib.Variant("(oa{sv})", (session_handle, options)),
            Gio.DBusCallFlags.NONE, -1, None
        )
        request_path = result.unpack()[0]
        print("SelectSources request path:", request_path)
        response = wait_for_response(connection, request_path)
        print("SelectSources response:", response)
        if response.get("code", 1) != 0:
            print("SelectSources failed with response:", response)
            pause_debug("SelectSources did not succeed. Pausing for debugging.")
            return False
        print("SelectSources succeeded.")
        return True
    except Exception as e:
        print(f"SelectSources failed: {e}")
        pause_debug("SelectSources failed. Pausing for debugging.")
        return False

def start_session(proxy, connection, session_handle):
    try:
        options = {
            "handle_token": GLib.Variant("s", uuid.uuid4().hex)
        }
        print("Starting session with session_handle:", session_handle)
        print("Start options:", options)
        result = proxy.call_sync(
            "Start",
            GLib.Variant("(osa{sv})", (session_handle, "", options)),
            Gio.DBusCallFlags.NONE, -1, None
        )
        request_path = result.unpack()[0]
        print("Start request path:", request_path)
        response = wait_for_response(connection, request_path)
        print("Start response:", response)
        streams = response["results"].get("streams", [])
        print("Streams array:", streams)
        if not streams:
            print("No streams returned in session start.")
            pause_debug("Start session did not return streams. Pausing for debugging.")
            return None
        print("Selected stream identifier (numeric):", streams[0][0])
        return streams[0][0]  # Return the numeric node ID.
    except Exception as e:
        print(f"Start failed: {e}")
        pause_debug("Start session failed. Pausing for debugging.")
        return None

def setup_adb():
    try:
        print("Setting up ADB reverse tunnel...")
        subprocess.run(["adb", "reverse", "tcp:5000", "tcp:5000"], check=True)
        return True
    except Exception as e:
        print(f"ADB error: {e}")
        pause_debug("ADB command failed. Pausing for debugging.")
        return False

def push_open():
    try:
        print("Opening stream in VLC")
        subprocess.run([
            "adb", "shell", "am", "start",
            "-n", "org.videolan.vlc/.gui.video.VideoPlayerActivity",
            "-d", "rtsp://127.0.0.1:5000/test",
        ], check=True)
        return True
    except Exception as e:
        print(f"ADB error: {e}")
        pause_debug("ADB command failed. Pausing for debugging.")
        return False

def get_node_name_from_id(node_id):
    try:
        dump = subprocess.run(["pw-dump"], check=True, stdout=subprocess.PIPE, text=True)
        data = json.loads(dump.stdout)
        for item in data:
            info = item.get("info", {})
            props = info.get("props", {})
            # Check if props has "node.id" matching the given node_id.
            if "node.id" in props and int(props["node.id"]) == int(node_id):
                # Prefer "node.name" if present.
                if "node.name" in props:
                    node_name = props["node.name"]
                elif "object.path" in props:
                    # Extract the part before ':' to mimic the old name.
                    node_name = props["object.path"].split(":")[0]
                elif "port.alias" in props:
                    node_name = props["port.alias"].split(":")[0]
                else:
                    node_name = None
                if node_name:
                    print(f"Found node name '{node_name}' for node id {node_id}")
                    return node_name
        print("No matching node found for id", node_id)
        return None
    except Exception as e:
        print("Error obtaining node name:", e)
        return None

def main():
    os.environ["PIPEWIRE_REMOTE"] = f"/run/user/{os.getuid()}/pipewire-0"
    print(f"PIPEWIRE_REMOTE set to {os.environ['PIPEWIRE_REMOTE']}")
    check_vkms()

    # Initialize GStreamer.
    Gst.init(None)

    proxy, connection = create_dbus_proxy()
    if proxy is None or connection is None:
        pause_debug("Failed to create DBus proxy. Pausing for debugging.")
        return

    session_handle = create_session(proxy, connection)
    if not session_handle:
        pause_debug("Session handle not obtained. Pausing for debugging.")
        return

    if not select_sources(proxy, connection, session_handle):
        pause_debug("Source selection failed. Pausing for debugging.")
        return

    stream_id = start_session(proxy, connection, session_handle)
    if not stream_id:
        pause_debug("Stream ID not obtained. Pausing for debugging.")
        return

    target_object = get_node_name_from_id(stream_id)
    if not target_object:
        pause_debug("Failed to determine target object from node id. Pausing for debugging.")
        return
    print(f"Using target object for pipewiresrc: {target_object}")

    if not setup_adb():
        pause_debug("ADB setup failed. Pausing for debugging.")
        return

    if not push_open():
        pause_debug("Failed to open VLC stream. Pausing for debugging.")
        return

    # Set up an RTSP server that will serve our screen capture.
    class MyRTSPMediaFactory(GstRtspServer.RTSPMediaFactory):
        def do_create_element(self, url):
            pipeline_str = (
                f"pipewiresrc target-object={target_object} ! video/x-raw,format=BGRA ! videoconvert ! timeoverlay ! "
                "vah264enc bitrate=3000 rate-control=cbr b-frames=0 key-int-max=15 ! "
                "rtph264pay aggregate-mode=1 name=pay0 pt=96"
            )
            print("Creating GStreamer pipeline:", pipeline_str)
            return Gst.parse_launch(pipeline_str)

    server = GstRtspServer.RTSPServer()
    server.set_service("5000")  # Set RTSP server port.
    mounts = server.get_mount_points()
    factory = MyRTSPMediaFactory()
    factory.set_shared(True)
    mounts.add_factory("/test", factory)
    server.attach(None)

    print("RTSP server is live at rtsp://127.0.0.1:5000/test")
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("Exiting due to KeyboardInterrupt.")

if __name__ == "__main__":
    main()
