# andmon

Extend your desktop to an Android device using ADB and Gstreamer

## Requirements

- Android device with USB debugging enabled.
- An implementation of xdg-desktop-portal with ScreenCast installed on your system.
- gstreamer-1.0
- ADB (Android Debug Bridge) installed.
- USB connection between your computer and Android device.

## Setup

1. **Connect Your Device**  
   Connect your Android device to your computer using a USB cable.

2. **Configure your virtual monitor**
   Create a virtual display via the method of your choice. On many systems you can use VKMS with 'sudo modprobe vkms'. On hyprland I use 'hyprctl output create headless virt-1'
   Some implementations of xdg-desktop-portal also allow for the creation of virtual displays through the screen selection dialog.

3. **Run the Script**  
   Install requirements and execute the script.
   
5. **Choose an encoder via sys-panel menu and start**
   x264 works best for me. Play around with it. Modify encoder settings in config.py. Play around with them.

   
## Notes
This is a rough draft. PRs and aggressive criticism are very welcome. All Nvidia encoders are untested.

## To-do
Make ADB exit gracefully
