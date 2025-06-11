#!/usr/bin/env python3

import sys
import signal

from stream_controller import StreamController

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore    import QTimer
    from tray            import SystemTray

    # Create Qt application
    app = QApplication(sys.argv)

    # Ctrl+C or kill quits Qt
    signal.signal(signal.SIGINT,  signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    # Create controller, pick a default codec
    controller = StreamController()
    controller.codec_name = controller.get_available_codecs()[0]

    # Create the system tray
    tray = SystemTray(controller)

    # Keep a small timer alive so Qt’s event loop can run
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(100)

    # Enter Qt’s event loop
    sys.exit(app.exec())
