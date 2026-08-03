# RaspiCam

Turn a Raspberry Pi into a small surveillance recorder with a web dashboard.

RaspiCam finds the cameras and drives attached to your Pi, streams them live in the browser, records around the clock in short segments, and gives you a scrubbable timeline to look back through. When you want to check in from somewhere else, it can open a public link through a free tunnel service without any account.

Everything runs on the Pi itself. No cloud service, no subscription, no account.

## Features

- **Any camera** — USB webcams, the official Pi camera modules on the ribbon cable, and RTSP or HTTP network cameras.
- **Pick your cameras** — every detected device is listed, you choose which ones to switch on.
- **Pick your storage** — microSD, USB sticks, external drives. RaspiCam shows what is mounted, how much space is left, and writes recordings where you tell it to.
- **Live view** — a responsive grid on any screen size, with a low bandwidth mode for slow connections.
- **Adjustable** — resolution, frame rate, bitrate, rotation and preview quality per camera.
- **Photos and recordings** — snapshot on demand, record by hand, or record continuously like a normal CCTV system.
- **Timeline playback** — pick a camera and a day, drag along the timeline, and play back from any moment.
- **Automatic cleanup** — the oldest footage is deleted when the drive gets close to full, so recording never stops.
- **Remote access** — one click starts a tunnel through Cloudflare, LocalTunnel, bore.pub, Pinggy or Serveo. Run several at the same time, and open any of them from a QR code.
- **Password protected** — you set a password the first time you open the dashboard.
- **Clean removal** — an uninstall button inside the app takes everything back off the device.

## Requirements

- Raspberry Pi 3, 4, 5 or Zero 2 W (anything that runs a 64-bit Raspberry Pi OS works best)
- Raspberry Pi OS or another Debian based Linux
- A camera, and ideally a USB drive for recordings

## Install

Run this on the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/OzikPutraJarwo/RaspiCam/main/install.sh | bash
```

That is the whole installation. It installs everything RaspiCam needs — ffmpeg, Python, Node.js and the tunnel clients (cloudflared, localtunnel, bore) — sets itself up in `/opt/raspicam`, and starts automatically on every boot.

When it finishes it prints the address to open, for example:

```
http://192.168.1.42:8080
```

Open that address from any device on the same network and set your password.

To use a different port, run `RASPICAM_PORT=9000 bash -c "$(curl -fsSL https://raw.githubusercontent.com/OzikPutraJarwo/RaspiCam/main/install.sh)"`.

## First steps

1. **Set a password.** This is the only account, and it protects the dashboard everywhere including through a tunnel.
2. **Open the Storage tab and choose where to save.** Nothing is recorded until you pick a location. A USB drive is strongly recommended so you are not wearing out the microSD card.
3. **Open the Cameras tab and press Detect.** Attached cameras show up in the list, press Add on the ones you want, and Start to switch them on. Network cameras are added with the *Add network camera* button by pasting an RTSP or HTTP address.
4. **Go to Live.** Tap a camera for a bigger view, take a photo, or start recording.

## Recording modes

Each camera has a recording mode in its settings:

| Mode | What it does |
| --- | --- |
| Off | Live view only, nothing is written to disk |
| Manual only | Recording starts and stops with the Record button |
| Continuous | Records non-stop as long as the camera is on |

Recordings are written as short MP4 segments (5 minutes by default) named after the time they started. Segments appear in the Playback timeline a few seconds after they close.

Under **Storage → Recording rules** you decide how long each segment is, at what disk usage the oldest footage starts being deleted, and how much free space to always keep. On a full drive RaspiCam deletes the oldest segments first and keeps recording.

Everything is stored in a plain folder tree, so you can also copy it off with a file manager:

```
<your drive>/RaspiCam/<camera id>/recordings/2026-08-03_14-30-00.mp4
<your drive>/RaspiCam/<camera id>/captures/2026-08-03_14-31-12.jpg
```

## Remote access

The Tunnel tab puts the dashboard on a public address without any signup. Press Start next to a provider and share or scan the link that appears. You can run several providers at once, which is useful when one of them is having a bad day.

| Provider | Notes |
| --- | --- |
| Cloudflare | HTTPS, fast and by far the most reliable. Try this one first. |
| LocalTunnel | HTTPS. Visitors see a warning page and must type your public IP once. |
| bore.pub | Plain HTTP on a random port, so no encryption. Keep those sessions short. |
| Pinggy | HTTPS over SSH. Free sessions end after 60 minutes and return on a new address. |
| Serveo | HTTPS over SSH. Community run and frequently offline. |

All five are installed for you, apart from Pinggy and Serveo which only need the SSH client that Raspberry Pi OS already has.

Tick **auto** next to a provider to bring its tunnel back up on every boot. Addresses from these free services change each time, so open the dashboard locally to read the new link.

**If a tunnel says "connect ... port 22: Connection timed out"** your network blocks outgoing SSH. That kills Serveo and Pinggy but not Cloudflare, which works over ordinary HTTPS.

Anyone with the link still needs your password, but treat these addresses as temporary and stop the tunnel when you are done.

## Managing the service

```bash
raspicam status      # is it running
raspicam logs        # follow the log
raspicam restart     # restart it
raspicam url         # show the local address
raspicam update      # get the newest version
raspicam uninstall   # remove RaspiCam
```

Settings live in `/opt/raspicam/data/config.json` and the recording index in `/opt/raspicam/data/raspicam.db`. Neither contains your video, only where to find it.

## Uninstalling

**Settings → Uninstall RaspiCam** removes the service, the program files, your settings and the tunnel clients that came with it, then closes the dashboard. Tick the box in that dialog if you also want every recording and photo deleted from the storage drive.

`sudo raspicam uninstall` does exactly the same thing from a terminal.

System packages such as ffmpeg, Python and Node.js are deliberately left in place, since other software on the device may be using them.

## Troubleshooting

**No cameras are detected.** Press Detect again after plugging the camera in. For a USB camera check that it appears with `ls /dev/video*`. For a Pi camera module check `rpicam-hello --list-cameras`. If you just installed RaspiCam, reboot once so the service picks up its camera permissions.

**A camera shows an error.** Open its settings and lower the resolution or frame rate. Some webcams only support a few exact combinations, and the ones they report are listed in the dropdowns. Switching the pixel format to MJPG usually helps on a Pi.

**Live view is slow over a tunnel.** Turn on *Low bandwidth* in the Live tab, and reduce *Live view size* and *Live view fps* in the camera settings. These only affect what you watch, not what is recorded.

**Recording never starts.** Check that a storage location is selected in the Storage tab and that the drive is still plugged in.

**Playback shows nothing for today.** Segments only appear once they are finished. Wait for the current segment to close, or press Rescan in the Storage tab.

**A USB drive is not listed.** RaspiCam only lists drives that are mounted. Plug it in with a desktop session running, or mount it yourself and press Rescan.

## License

MIT. See [LICENSE](LICENSE).
