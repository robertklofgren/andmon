#!/usr/bin/env python3
import sys
import os
import time
import uuid
import subprocess
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GLib, Gio, GObject

# Global variables for screen capture and MJPEG streaming.
latest_frame = None
frame_lock = threading.Lock()


# Utility functions and debugging

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
            data = f.read().strip()
            print("Current /proc/modules content:", data)
            if "vkms" not in data:
                print("vkms not found; loading it...")
                subprocess.run(["sudo", "modprobe", "vkms"], check=True)
            else:
                print("vkms already loaded.")
    except Exception as e:
        print(f"VKMS error: {e}")
        pause_debug("VKMS error encountered. Pausing for debugging.")


# ScreenCast Setup via D-Bus

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
            loop.quit()
    sub = connection.signal_subscribe(
        None, "org.freedesktop.portal.Request", "Response",
        request_path, None, Gio.DBusSignalFlags.NO_MATCH_RULE, handler)
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
            Gio.DBusCallFlags.NONE, -1, None)
        request_path = result.unpack()[0]
        print("CreateSession request path:", request_path)
        response = wait_for_response(connection, request_path)
        print("CreateSession response:", response)
        session_handle = response["results"].get("session_handle")
        if not session_handle:
            pause_debug("Session handle not received. Pausing for debugging.")
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
            "types": GLib.Variant("u", 5),
            "cursor_mode": GLib.Variant("u", 2),
            "handle_token": GLib.Variant("s", uuid.uuid4().hex)
        }
        print("Selecting sources with session_handle:", session_handle)
        result = proxy.call_sync(
            "SelectSources",
            GLib.Variant("(oa{sv})", (session_handle, options)),
            Gio.DBusCallFlags.NONE, -1, None)
        request_path = result.unpack()[0]
        response = wait_for_response(connection, request_path)
        if response.get("code", 1) != 0:
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
        options = {"handle_token": GLib.Variant("s", uuid.uuid4().hex)}
        print("Starting session with session_handle:", session_handle)
        result = proxy.call_sync(
            "Start",
            GLib.Variant("(osa{sv})", (session_handle, "", options)),
            Gio.DBusCallFlags.NONE, -1, None)
        request_path = result.unpack()[0]
        response = wait_for_response(connection, request_path)
        streams = response["results"].get("streams", [])
        if not streams:
            pause_debug("Start session did not return streams. Pausing for debugging.")
            return None
        print("Selected stream identifier (numeric):", streams[0][0])
        return streams[0][0]  #node id
    except Exception as e:
        print(f"Start failed: {e}")
        pause_debug("Start session failed. Pausing for debugging.")
        return None

def get_node_name_from_id(node_id):
    try:
        dump = subprocess.run(["pw-dump"], check=True, stdout=subprocess.PIPE, text=True)
        data = json.loads(dump.stdout)
        for item in data:
            props = item.get("info", {}).get("props", {})
            if "node.id" in props and int(props["node.id"]) == int(node_id):
                node_name = props.get("node.name") or props.get("object.path", "").split(":")[0] or props.get("port.alias", "").split(":")[0]
                if node_name:
                    print(f"Found node name '{node_name}' for node id {node_id}")
                    return node_name
        print("No matching node found for id", node_id)
        return None
    except Exception as e:
        print("Error obtaining node name:", e)
        return None

# GStreamer Appsink Callback for MJPEG

def on_new_sample(sink):
    global latest_frame
    sample = sink.emit("pull-sample")
    if sample:
        buf = sample.get_buffer()
        success, map_info = buf.map(Gst.MapFlags.READ)
        if success:
            with frame_lock:
                latest_frame = map_info.data  # JPEG-encoded bytes
            buf.unmap(map_info)
        return Gst.FlowReturn.OK
    return Gst.FlowReturn.ERROR


# HTTP MJPEG Server
class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            # HTML page that embeds the MJPEG stream and requests full screen on tap.
            html = """
<!DOCTYPE html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
      html, body {
        margin: 0;
        padding: 0;
        height: 100%;
        background-color: black;
        overflow: hidden;
      }
      #stream {
        width: 100vw;
        height: 100vh;
        object-fit: contain;
        background-color: black;
      }
      #overlay {
        position: absolute;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        color: white;
        font-size: 24px;
        display: flex;
        justify-content: center;
        align-items: center;
        background-color: rgba(0,0,0,0.5);
        z-index: 10;
      }
    </style>
  </head>
  <body>
    <div id="overlay">Tap to go Full Screen</div>
    <img id="stream" src="/mjpeg" alt="MJPEG Stream"/>
    <script>
      document.addEventListener('click', function() {
          var overlay = document.getElementById("overlay");
          if(overlay) { overlay.style.display = "none"; }
          if (document.documentElement.requestFullscreen) {
              document.documentElement.requestFullscreen();
          } else if (document.documentElement.webkitRequestFullscreen) {
              document.documentElement.webkitRequestFullscreen();
          } else if (document.documentElement.mozRequestFullScreen) {
              document.documentElement.mozRequestFullScreen();
          } else if (document.documentElement.msRequestFullscreen) {
              document.documentElement.msRequestFullscreen();
          }
      });
    </script>
  </body>
</html>
"""
            self.wfile.write(html.encode())
        elif self.path == "/mjpeg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        frame = latest_frame
                    if frame:
                        self.wfile.write(b"--FRAME\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.035)
            except Exception as e:
                print("Client disconnected:", e)
        else:
            self.send_response(404)
            self.end_headers()

def run_mjpeg_http_server():
    server_address = ('', 5000)
    httpd = HTTPServer(server_address, MJPEGHandler)
    print("MJPEG HTTP server running on port 5000")
    httpd.serve_forever()


# ADB Setup and Browser launch

def setup_adb():
    try:
        print("Setting up ADB reverse tunnel for port 5000...")
        subprocess.run(["adb", "reverse", "tcp:5000", "tcp:5000"], check=True)
        return True
    except Exception as e:
        print(f"ADB error: {e}")
        pause_debug("ADB command failed. Pausing for debugging.")
        return False

def push_open():
    try:
        print("Opening full-screen MJPEG client in browser on Android")
        subprocess.run([
            "adb", "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", "http://127.0.0.1:5000/"
        ], check=True)
        return True
    except Exception as e:
        print(f"ADB error: {e}")
        pause_debug("ADB command failed. Pausing for debugging.")
        return False


# MJPEG Pipeline Setup

def main():
    os.environ["PIPEWIRE_REMOTE"] = f"/run/user/{os.getuid()}/pipewire-0"
    print(f"PIPEWIRE_REMOTE set to {os.environ['PIPEWIRE_REMOTE']}")
    check_vkms()

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

    mjpeg_thread = threading.Thread(target=run_mjpeg_http_server, daemon=True)
    mjpeg_thread.start()

    if not setup_adb():
        pause_debug("ADB setup failed. Pausing for debugging.")
        return
    if not push_open():
        pause_debug("Failed to open MJPEG client in browser. Pausing for debugging.")
        return

    # Build the GStreamer pipeline: capture, convert, JPEG encode, and push frames to appsink.
    pipeline_str = (
        f"pipewiresrc target-object={target_object} ! "
        "queue max-size-buffers=1 leaky=downstream ! "
        "videorate ! video/x-raw,format=BGRA,framerate=30/1 ! "
        "videoconvert ! "
        "jpegenc quality=80 ! "
        "appsink name=mysink emit-signals=true max-buffers=1 drop=true"
    )
    print("Creating GStreamer pipeline:", pipeline_str)
    pipeline = Gst.parse_launch(pipeline_str)

    appsink = pipeline.get_by_name("mysink")
    if not appsink:
        print("Error: could not retrieve appsink from pipeline")
        sys.exit(1)
    appsink.connect("new-sample", on_new_sample)

    pipeline.set_state(Gst.State.PLAYING)
    print("MJPEG pipeline is running. Capturing screen...")

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("Exiting due to KeyboardInterrupt.")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
