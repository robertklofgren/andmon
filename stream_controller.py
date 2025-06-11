
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gst, GLib
import threading
import subprocess
import asyncio
import signal
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import websockets
import json

from config import WS_PORT, HTTP_PORT, HOST, CODEC_TABLE, PREFERRED_ORDER
from portal import create_session, select_sources, start_session, close_session
SERVER_CODECS = []

def get_server_available_codecs() -> list[str]:
    available = []
    for key, (pipeline_str, _) in CODEC_TABLE.items():
        plugin_name = pipeline_str.split()[0]
        if Gst.ElementFactory.find(plugin_name) is not None:
            available.append(key)
        else:
            print(f"[warning] encoder '{key}' skipped: plugin '{plugin_name}' not found")
    return available


def _init_codecs():
    Gst.init(None)
    sc = get_server_available_codecs()
    po = [c for c in PREFERRED_ORDER if c in sc]
    if not po:
        raise RuntimeError("No usable codecs found—please install at least one encoder plugin.")
    return sc, po


# -----------------------------------------------------------------------------
# init_msg helper
# -----------------------------------------------------------------------------
def init_msg(codec_key: str) -> str:
    """Return the JSON handshake message for the given codec."""
    _, wc_string = CODEC_TABLE[codec_key]
    return json.dumps({"type": "config", "codec": wc_string})


# -----------------------------------------------------------------------------
# HTTP static file handler
# -----------------------------------------------------------------------------
class Static(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).with_name("static")), **kwargs)


# -----------------------------------------------------------------------------
# ADB reverse helper
# -----------------------------------------------------------------------------
def try_adb_reverse() -> bool:
    """
    Attempt to do `adb reverse` for HTTP and WS ports, and launch the client browser.
    Returns True if succeeded; False if adb not found or adb reverse failed
    """
    from shutil import which

    if which("adb") is None:
        print("Server: adb not found")
        return False

    launch_cmd = [
        "adb",
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        f"http://127.0.0.1:{HTTP_PORT}",
    ]

    try:
        subprocess.run(
            ["adb", "reverse", f"tcp:{HTTP_PORT}", f"tcp:{HTTP_PORT}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["adb", "reverse", f"tcp:{WS_PORT}", f"tcp:{WS_PORT}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(launch_cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Server: ADB reverse + launch done.")
        return True

    except subprocess.CalledProcessError:
        print("Server: ADB reverse already exists or failed; try 'adb kill-server'")
        return False

    except Exception as e:
        print("Server: adb error", e)
        return False


class StreamController:
    """
    Manages:
      - PipeWire portal session (screen capture)
      - GStreamer pipeline (appsink → Python)
      - HTTP server (static files)
      - WebSocket server (video frames)
      - GLib main loop and cleanup
    """

    def __init__(self):
        # GStreamer init
        Gst.init(None)

        # Probe available codecs 
        global SERVER_CODECS, PREFERRED_ORDER
        if not SERVER_CODECS:
            SERVER_CODECS, PREFERRED_ORDER = _init_codecs()

        self.available_codecs = SERVER_CODECS
        self.preferred_order = PREFERRED_ORDER

        # Portal / PipeWire state
        self.session = None
        self.pw_id = None

        # GStreamer pipeline
        self.pipeline = None

        # HTTP & WS servers
        self.httpd = None
        self.http_thread = None
        self.ws_thread = None

        # GLib main loop
        self.loop = None
        self.glib_thread = None

        # Active WebSocket connection
        self.ws_conn = None
        self.push_loop = None  # asyncio loop used for sending frames

        # Selected codec for next “Start Stream”
        self.codec_name = None
        self.forced_enc = None

        # Scratch buffer for minimal‐allocation copies
        self._scratch = bytearray(0)

    def get_available_codecs(self):
        ordered = [c for c in PREFERRED_ORDER if c in self.available_codecs]
        rest = [c for c in self.available_codecs if c not in ordered]
        return ordered + rest


    def set_codec(self, key: str):
        self.codec_name = key

    def start_screen_capture(self):
        # Create a PipeWire portal session and store the pw_id.
        self.session = create_session()
        select_sources(self.session)
        self.pw_id = start_session(self.session)
        print("Server: PipeWire node id", self.pw_id)

    def stop_screen_capture(self):
        # Tear down the GStreamer pipeline and close the portal session.
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        if self.session:
            close_session(self.session)
            self.session = None
            self.pw_id = None

    def build_new_pipeline(self, name: str):
        """
        Build a new GStreamer pipeline under the chosen encoder.
        """
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        enc_spec, _ = CODEC_TABLE[name]
        print(f"Building pipeline with codec: {name}, spec: {enc_spec}")

        desc = (
            f"pipewiresrc path={self.pw_id} ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            "videorate drop-only=true ! video/x-raw,framerate=30/1 ! "
            "videoconvert ! "
            f"{enc_spec} ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            "appsink name=sink emit-signals=true sync=false drop=false max-buffers=1"
        )
        print(f"Pipeline description: {desc}")

        pl = Gst.parse_launch(desc)
        if not pl:
            raise RuntimeError("Gst.parse_launch failed for: " + desc)

        sink = pl.get_by_name("sink")
        if not sink:
            raise RuntimeError("Failed to get appsink element from pipeline")

        sink.connect("new-sample", self.on_new_sample)
        pl.set_state(Gst.State.PLAYING)
        self.pipeline = pl

    def on_new_sample(self, sink) -> Gst.FlowReturn:
        """
        Pull a sample, prepend PTS, and send via WebSocket if a client is connected.
        We copy into a reusable bytearray (_scratch) to minimize per-frame allocations.
        """
        sample = sink.emit("pull-sample")
        buf    = sample.get_buffer()
        pts    = buf.pts
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR

        size = info.size
        if len(self._scratch) < size:
            self._scratch = bytearray(size)
        self._scratch[:size] = info.data
        payload = bytes(self._scratch[:size])
        buf.unmap(info)

        pkt = pts.to_bytes(8, "big") + payload
        if self.ws_conn is not None:
            try:
                from asyncio import run_coroutine_threadsafe
                run_coroutine_threadsafe(self.ws_conn.send(pkt), self.push_loop)
            except Exception:
                pass  # If WS closed, drop

        return Gst.FlowReturn.OK

    def start_http_ws(self):
        """Spawn HTTP server and WebSocket server on background threads."""
        ThreadingHTTPServer.allow_reuse_address = True
        self.httpd = ThreadingHTTPServer((HOST, HTTP_PORT), Static)
        self.http_thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True
        )
        self.http_thread.start()

        # WebSocket: separate asyncio thread
        def run_ws():
            asyncio.run(self.ws_main())

        self.ws_thread = threading.Thread(target=run_ws, daemon=True)
        self.ws_thread.start()

    def stop_http_ws(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

        if self.http_thread:
            self.http_thread.join()
            self.http_thread = None

    async def ws_handler(self, ws):
        """
        On new WebSocket:
          1) Negotiate codec
          2) Send {type:"config", codec:…}
          3) Build pipeline
          4) Send {type:"codec_info", codec:…}
          5) Keep alive until client disconnects
        """
        self.ws_conn = ws
        self.push_loop = asyncio.get_running_loop()
        print("Server: WS connect", ws.remote_address)

        # Codec negotiation
        if self.forced_enc:
            self.codec_name = self.forced_enc
            _ = await ws.recv()
        else:
            first = await ws.recv()
            try:
                offered = json.loads(first)["codecs"]
            except Exception:
                offered = ["mjpeg"]

            chosen = None
            for key in self.preferred_order:
                wc = CODEC_TABLE[key][1]
                if key in offered or wc in offered:
                    chosen = key
                    break
            self.codec_name = chosen if chosen else "mjpeg"

        # Send the chosen config
        await ws.send(init_msg(self.codec_name))

        # Build pipeline
        self.build_new_pipeline(self.codec_name)

        # Inform client of WebCodecs string
        await ws.send(json.dumps({
            "type": "codec_info",
            "codec": CODEC_TABLE[self.codec_name][1]
        }))

        # Stay open until client disconnects
        try:
            await ws.wait_closed()
        finally:
            print("Server: WS client disconnected")
            if self.ws_conn is ws:
                self.ws_conn = None
            self.codec_name = None

    async def ws_main(self):
        """
        Serve WebSocket connections until GLib.MainLoop quits.
        If the port is already in use, catch and print a friendly message.
        """
        try:
            async with websockets.serve(self.ws_handler, HOST, WS_PORT):
                await asyncio.Future()  # run until loop.quit()
        except OSError as e:
            if e.errno == 98:  # Address already in use
                print(f"Server: WS port {WS_PORT} already in use; did you stop the previous stream?")
                return
            raise

    def start_stream(self, forced_encoder: str = None):
        """
        Begin streaming:
          1) Remember forced_encoder
          2) Start PipeWire portal
          3) Attempt ADB reverse, abort if it fails
          4) Start HTTP + WS
          5) Launch GLib.MainLoop in background thread
        """
        self.forced_enc = forced_encoder or self.codec_name

        # collect pw_id
        self.start_screen_capture()

        # ADB reverse (USB → localhost), abort if it fails
        if not try_adb_reverse():
            self.stop_screen_capture()
            print("Server: Aborting because ADB reverse failed.")
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().quit()
            return

        # HTTP + WS
        self.start_http_ws()

        # GLib loop
        def run_glib():
            self.loop = GLib.MainLoop()
            GLib.unix_signal_add(
                GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda *_: self.graceful_exit()
            )
            GLib.unix_signal_add(
                GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *_: self.graceful_exit()
            )
            self.loop.run()

        self.glib_thread = threading.Thread(target=run_glib, daemon=True)
        self.glib_thread.start()

    def stop_stream(self):
        self.stop_http_ws()
        self.stop_screen_capture()
        if self.loop:
            self.loop.quit()
            self.loop = None


    def graceful_exit(self) -> bool:
        """Called on SIGINT/SIGTERM inside GLib loop—cleanup and ask Qt to quit."""
        print("Server: cleaning up…")
        if self.session:
            self.stop_stream()
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().quit()
        except Exception:
            pass
        return True
