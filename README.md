# extendroid

A quick and dirty script to extend your desktop to an Android device using xdg-desktop-portal, Gstreamer, and ADB.

**CAVEAT:** You WILL need to wangjangle this script to run on your system. It is the roughest kind of rough draft.

## Requirements

- Android device with USB debugging enabled.
- ADB (Android Debug Bridge) installed.
- USB connection between your computer and Android device.
- xdg-desktop-portal installed on your system.
- Gstreamer with gst-plugins-ugly

## Setup

1. **Connect Your Device**  
   Connect your Android device to your computer using a USB cable.

2. **Customize the Gstreamer Pipeline**  
   Edit the Gstreamer pipeline in the script to use an encoder of your choice.

3. **Run the Script**  
   Execute the script. The first time it runs, you might need to set the resolution, position, and orientation of your virtual monitor.


## Notes
extendroid.py was a PoC that I'm leaving up to remind myself of the frustrations of Dbus.
Use extendroidjpeg.py for an easy solution with acceptable performance.
