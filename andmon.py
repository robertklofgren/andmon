#!/usr/bin/env python3
import sys
import uuid
import subprocess
import threading
import signal
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib


#  Helpers for portal calls via dbus‑python

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
portal_obj = bus.get_object('org.freedesktop.portal.Desktop',
                            '/org/freedesktop/portal/desktop')
sc = dbus.Interface(portal_obj, 'org.freedesktop.portal.ScreenCast')

def wait_for_response(request_path):
    loop = GLib.MainLoop()
    result = {}

    def on_response(code, results):
        result['code'] = code
        result['results'] = {k: v for k, v in results.items()}
        loop.quit()

    bus.add_signal_receiver(
        on_response,
        signal_name='Response',
        dbus_interface='org.freedesktop.portal.Request',
        path=request_path)

    loop.run()
    return result.get('code', -1), result.get('results', {})

def create_session():
    token = uuid.uuid4().hex
    opts = {
        'session_handle_token': dbus.String(token),
        'handle_token':         dbus.String(token),
        'types':                dbus.UInt32(7),
        'cursor_mode':          dbus.UInt32(2),
    }
    request_path = sc.CreateSession(opts)
    code, res = wait_for_response(request_path)
    if code != 0 or 'session_handle' not in res:
        raise RuntimeError(f'CreateSession failed ({code}): {res}')
    return res['session_handle']

def select_sources(session_handle):
    token = uuid.uuid4().hex
    opts = {
        'types':       dbus.UInt32(7),
        'multiple':    dbus.Boolean(False),
        'persist_mode':dbus.UInt32(0),
        'cursor_mode': dbus.UInt32(2),   # 2 == EMBED
        'handle_token':dbus.String(token),
    }

    request_path = sc.SelectSources(session_handle, opts)
    code, _ = wait_for_response(request_path)
    if code != 0:
        raise RuntimeError(f'SelectSources failed ({code})')
    return True

def start_session(session_handle):
    token = uuid.uuid4().hex
    opts = {
        'handle_token': dbus.String(token),
    }
    request_path = sc.Start(session_handle, '', opts)
    code, res = wait_for_response(request_path)
    if code != 0 or 'streams' not in res or not res['streams']:
        raise RuntimeError(f'Start failed ({code}): {res}')
    return res['streams'][0][0]

#  MJPEG HTTP server + GStreamer pipeline

latest_frame = None
frame_lock = threading.Lock()

class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode())
        elif self.path == '/mjpeg':
            self.send_response(200)
            self.send_header('Content-Type',
                             'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        frame = latest_frame
                    if frame:
                        header = (
                            '--FRAME\r\n'
                            'Content-Type: image/jpeg\r\n'
                            f'Content-Length: {len(frame)}\r\n\r\n'
                        ).encode('ascii')
                        self.wfile.write(header + frame + b'\r\n')
                    time.sleep(0.1)
            except Exception:
                return
        else:
            self.send_response(404)
            self.end_headers()

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    html, body {
      margin: 0;
      padding: 0;
      height: 100%;
      position: relative;
      background-color: black;
      overflow: hidden;
    }
    #stream {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      object-fit: contain;
      border: none;
    }
    #overlay {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
      color: white;
      font-size: 24px;
      background-color: rgba(0,0,0,0.5);
      pointer-events: none;
      z-index: 10;
    }
  </style>
</head>
<body>
  <div id="overlay">Tap to go Full Screen</div>
  <img id="stream" src="/mjpeg" />
  <script>
    document.addEventListener('click', () => {
      const ov = document.getElementById('overlay');
      if (ov) ov.style.display = 'none';
      const doc = document.documentElement;
      if (doc.requestFullscreen) doc.requestFullscreen();
      else if (doc.webkitRequestFullscreen) doc.webkitRequestFullscreen();
    });
  </script>
</body>
</html>
"""


def on_new_sample(sink):
    global latest_frame
    sample = sink.emit('pull-sample')
    if sample:
        buf = sample.get_buffer()
        success, info = buf.map(Gst.MapFlags.READ)
        if success:
            with frame_lock:
                latest_frame = info.data
            buf.unmap(info)
        return Gst.FlowReturn.OK
    return Gst.FlowReturn.ERROR

def run_http():
    HTTPServer(('', 5000), MJPEGHandler).serve_forever()

def setup_adb():
    subprocess.run(['adb','reverse','tcp:5000','tcp:5000'], check=True)

def push_open():
    subprocess.run([
        'adb','shell','am','start',
        '-a','android.intent.action.VIEW',
        '-d','http://127.0.0.1:5000/'
    ], check=True)

def launch_pipeline(stream_id):
    threading.Thread(target=run_http, daemon=True).start()
    setup_adb()
    push_open()
    pipeline_str = (
        f'pipewiresrc path={stream_id} ! videorate ! '
        'video/x-raw,framerate=30/1 ! '
        'queue max-size-buffers=10 max-size-time=35000000 leaky=downstream ! '
        'jpegenc quality=25 ! appsink name=mysink emit-signals=true '
        'max-buffers=1 drop=true'
    )
    pipeline = Gst.parse_launch(pipeline_str)
    sink = pipeline.get_by_name('mysink')
    sink.connect('new-sample', on_new_sample)
    pipeline.set_state(Gst.State.PLAYING)
    print('Streaming MJPEG on http://127.0.0.1:5000/ …')
    GLib.MainLoop().run()

#  Clean‑up handler

session_handle = None

def cleanup_and_exit(signum, frame):
    if session_handle:
        try:
            sc.Close(session_handle)
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup_and_exit)
signal.signal(signal.SIGTERM, cleanup_and_exit)

#  Main

if __name__ == '__main__':
    Gst.init(None)
    session_handle = create_session()
    select_sources(session_handle)
    stream = start_session(session_handle)
    launch_pipeline(stream)
