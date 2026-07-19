---
title: Hardware
subtitle: Leaders on USB, YAMs on CAN
section: Set up
order: 3
next_teaser: >-
  every leader and every arm is accounted for. The next chapter measures the
  leaders.
---

Two buses, two identities. The SO-101 leaders enumerate over USB and are
addressed by their stable serial alias; the YAM followers live on CAN channels
and are addressed by channel name.

## Leader identity

Always work from `/dev/serial/by-id`. The transient `/dev/ttyACM*` name changes
between plug-ins, and the calibration file is keyed by the by-id basename:

```bash
ls -l /dev/serial/by-id
```

Leaders appear as `usb-1a86_USB_Single_Serial_<serial>-if00`. That full string —
not the serial alone, not the `ttyACM` path — is the key under `leader_arms` in
the config, and it is what every tool resolves back to.

{% capture body %}
`FeetechPortIdentity.resolve` accepts a `/dev/ttyACM*` path, a full by-id path,
or a bare by-id basename, but it always resolves to the by-id name. If
`/dev/serial/by-id` doesn't exist on the host, every tool refuses to start —
`Serial identity directory not found`.
{% endcapture %}
{% include callout.html type="info" title="One identity, three spellings" body=body %}

## CAN channels

Inspect the channels without changing them:

```bash
ip -details link show can0
ip -details link show can1
```

The YAM arms run at 1 Mbit/s. If a channel is missing or down, that's a host
configuration problem — fix it at the OS level rather than pointing the tools at
a different interface name.

## Power

Each SO-101 leader needs its own power supply. Sharing one across two leaders
causes servo dropouts that surface later as flaky health checks, corrupt reads
during calibration, and jumps during teleop. If a health check reports
intermittent ping counts, suspect power before you suspect configuration.

## Cameras

The RealSense cameras are only needed for the recording pipeline. To find out
which physical camera is which, snapshot them one at a time:

```bash
uv run scripts/check_cameras.py
```

Each camera is opened alone — deliberately, to avoid USB bandwidth conflicts —
at 640×480 RGB, and a labeled JPG is written to `scripts/cam_snapshots/`. Open
the images to map serial numbers to top and wrist positions; nothing infers that
for you.

{% capture body %}
The camera device is exclusive. If the dashboard is running it holds the
cameras, and `check_cameras.py` will report `NO FRAME` for every one of them.
Stop the dashboard first.
{% endcapture %}
{% include callout.html type="warn" title="One process owns the cameras" body=body %}
