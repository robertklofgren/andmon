# extendroid

A quick and dirty script to extend your desktop to an Android device using xdg-desktop-portal, Gstreamer, and ADB.


## Requirements

- Android device with [mpv-android](https://github.com/mpv-player/mpv-android) installed.
- USB connection between your computer and Android device.
- xdg-desktop-portal installed on your system.
- Gstreamer with your preferred encoder.
- ADB (Android Debug Bridge) installed.

## Setup

1. **Install mpv-android**  
   Download and install [mpv-android](https://github.com/mpv-player/mpv-android) on your Android device.

2. **Configure mpv-android**  
   Open mpv-android on your device and edit the `mpv.conf` file to include the following settings:

   ```conf
   profile=low-latency
   no-cache
   playback-speed=1.01
   ```

3. **Connect Your Device**  
   Connect your Android device to your computer using a USB cable.

4. **Customize the Gstreamer Pipeline**  
   Edit the Gstreamer pipeline in the script to use an encoder of your choice.

5. **Run the Script**  
   Execute the script. The first time it runs, you might need to set the resolution, position, and orientation of your virtual monitor.



## Work In Progress

- Investigate WebRTC for potentially improved streaming.
- Develop a client app to take advantage of media3.
- Write a helper function to build the Gstreamer pipeline based on available encoders on the host.

