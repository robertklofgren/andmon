# -----------------------------------------------------------------------------
# Network configuration
# -----------------------------------------------------------------------------
HOST = "0.0.0.0"
HTTP_PORT = 8000
WS_PORT = 8767

# -----------------------------------------------------------------------------
# Codec definitions (pipeline fragment + WebCodecs string)
# -----------------------------------------------------------------------------
CODEC_TABLE = {
    "vah265": (
        "vah265enc target-usage=7 rate-control=cbr bitrate=18000 key-int-max=1 ! "
        "h265parse config-interval=1 ! "
        "video/x-h265,stream-format=byte-stream,alignment=au",
        "hev1.1.6.L93.B0",
    ),
    "vah264": (
        "vah264enc target-usage=7 rate-control=cbr cabac=false bitrate=18000 key-int-max=1 ! "
        "h264parse config-interval=1 ! "
        "video/x-h264,stream-format=byte-stream,alignment=au",
        "avc1.42001E",
    ),
    "vaapih264": (
        "vaapih264enc rate-control=cbr bitrate=8000 ! "
        "h264parse config-interval=1 ! "
        "video/x-h264,stream-format=byte-stream,alignment=au",
        "avc1.42001E",
    ),
    "nvh264": (
        "nvh264enc bitrate=20000 ! "
        "h264parse config-interval=1 ! "
        "video/x-h264,stream-format=byte-stream,alignment=au",
        "avc1.42001E",
    ),
    "x264": (
        "x264enc tune=zerolatency speed-preset=ultrafast "
        "bitrate=18000 "
        "key-int-max=1 ! "
        "h264parse config-interval=1 ! "
        "video/x-h264,profile=baseline,stream-format=byte-stream,alignment=au",
        "avc1.42001E",
    ),
    "vp8": (
        "vp8enc deadline=1 cpu-used=8 keyframe-max-dist=5 target-bitrate=2000000 ! "
        "video/x-vp8,stream-format=byte-stream,alignment=au",
        "vp8",
    ),
    "mjpeg": (
        "jpegenc idct-method=float quality=40 ! image/jpeg",
        "mjpeg",
    ),
    "vp9": (
        "vp9enc deadline=1 keyframe-max-dist=5 target-bitrate=2000000 ! "
        "video/x-vp9,stream-format=byte-stream,alignment=au",
        "vp09.00.10.08",
    ),
    "x265": (
        "x265enc tune=zerolatency speed-preset=ultrafast key-int-max=1 bitrate=15000 ! "
        "h265parse config-interval=1 ! "
        "video/x-h265,profile=main,stream-format=byte-stream,alignment=au",
        "hev1.1.6.L93.B0",
    ),
}

# A default preference order; will be filtered against installed plugins:
PREFERRED_ORDER = [
   "vah265", "vah264", "vaapih264", "nvh264", "x264", "mjpeg", "x265", "vp8",  "vp9"
]
