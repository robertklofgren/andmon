#!/usr/bin/env python3

import os, signal

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction, QActionGroup
from stream_controller import StreamController 

class SystemTray:
    def __init__(self, controller: StreamController):
        self.controller = controller

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon.fromTheme("video-display"))
        self.tray.setToolTip("andmon")
        self.menu = QMenu()

        # Start / Stop
        self.start_action = self.menu.addAction("Start Stream")
        self.start_action.triggered.connect(self.on_start)

        self.stop_action = self.menu.addAction("Stop Stream")
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.on_stop)

        self.menu.addSeparator()

        # Encoder submenu
        self.encoder_menu = self.menu.addMenu("Encoder")
        self.encoder_group = QActionGroup(self.encoder_menu)
        self.encoder_group.setExclusive(True)

        # Populate
        for codec_key in self.controller.get_available_codecs():
            act = self.encoder_menu.addAction(codec_key)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, c=codec_key: self.on_select_encoder(c))
            self.encoder_group.addAction(act)
            if codec_key == self.controller.codec_name:
                act.setChecked(True)

        self.menu.addSeparator()

        # Status
        self.status_action = self.menu.addAction("Streaming stopped")
        self.status_action.setEnabled(False)

        self.menu.addSeparator()

        # Exit
        self.exit_action = self.menu.addAction("Exit")
        self.exit_action.triggered.connect(self.on_exit)

        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def on_start(self):
        # Disable “Start,” enable “Stop,” update status
        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.status_action.setText("Streaming active")

        # Start streaming
        self.controller.start_stream(forced_encoder=self.controller.codec_name)

    def on_stop(self):
        # Disable “Stop,” enable “Start,” update status
        self.stop_action.setEnabled(False)
        self.start_action.setEnabled(True)
        self.status_action.setText("Streaming stopped")
        self.controller.stop_stream()

    def on_select_encoder(self, codec_key):
        self.controller.set_codec(codec_key)
        self.tray.setToolTip("andmon")

    def on_exit(self):
        self.controller.stop_stream()
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()
