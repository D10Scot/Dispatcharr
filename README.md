# 🎬 Mino — Your Ultimate IPTV & Stream Management Companion

<p align="center">
  <img src="frontend/src/images/logo.png" height="200" alt="Mino Logo" />
</p>

---

## 📖 What is Mino?

Mino is an **open-source powerhouse** for managing IPTV streams, EPG data, and VOD content with elegance and control.\
Born from necessity and built with passion, it started as a personal project by **[OkinawaBoss](https://github.com/OkinawaBoss)** and evolved with contributions from legends like **[dekzter](https://github.com/dekzter)**, **[SergeantPanda](https://github.com/SergeantPanda)** and **[Seth](https://github.com/sethwv)**.

> Think of Mino as the \*arr family's IPTV cousin — simple, smart, and designed for streamers who want reliability and flexibility.

---

## 🎯 What Can I Do With Mino?

Mino empowers you with complete IPTV control. Here are some real-world scenarios:

💡 **Consolidate Multiple IPTV Sources**\
Combine streams from multiple providers into a single interface. Manage, filter, and organize thousands of channels with ease.

📺 **Integrate with Media Centers**\
Use HDHomeRun emulation to add virtual tuners to **Plex**, **Emby**, or **Jellyfin**. They'll discover Mino as a live TV source and can record programs directly to their own DVR libraries.

📼 **Record with Built-in DVR**\
Schedule one-time or recurring recordings from the TV Guide, manage series rules, and optionally strip commercials with Comskip. Watch recordings while they're still in progress.

📡 **Create a Personal TV Ecosystem**\
Merge live TV channels with custom EPG guides from XMLTV or Schedules Direct. Generate schedules or use auto-matching to align channels with program data. Export as M3U, Xtream Codes API, or HDHomeRun device.

⏪ **Watch Catch-up / Timeshift**\
Replay recent programs from Xtream Codes providers that advertise archives. Catch-up sessions show up on the Stats page alongside live and VOD, with per-user and global controls.

🔧 **Transcode & Optimize Streams**\
Configure output profiles with FFmpeg transcoding to optimize streams for different clients (reduce bandwidth, standardize formats, or add audio normalization).

🔐 **Centralize VPN Access**\
Run Mino through a VPN container (like Gluetun) so all streams route through a single VPN connection. Your clients access geo-blocked content without needing individual VPNs, reducing bandwidth overhead and simplifying network management.

🚀 **Monitor & Manage in Real-Time**\
Track live, VOD, and catch-up sessions, client connections, and bandwidth usage with live statistics. Monitor buffering events and stream quality. Automatic failover keeps viewers connected when streams fail—seamlessly switching to backup sources without interruption.

👥 **Share Access Safely**\
Create multiple user accounts with granular permissions. Share streams via M3U playlists or Xtream Codes API while controlling which users access which channels, profiles, or features. Network-based access restrictions available for additional security.

🔌 **Extend with Plugins**\
Build custom integrations using Mino's robust plugin system. Automate tasks, connect to external services, or add entirely new workflows.

---

## ✨ Why You'll Love Mino

✅ **Stream Proxy & Relay** — Intercept and proxy IPTV streams with real-time client management\
✅ **M3U & Xtream Codes** — Import, filter, and organize playlists with multiple backend support\
✅ **EPG Matching & Generation** — XMLTV, Schedules Direct, or dummy guides; auto-match EPG to channels or generate custom schedules\
✅ **Built-in DVR** — Schedule recordings and series rules from the guide, with optional Comskip and in-progress playback\
✅ **XC Catch-up / Timeshift** — Proxy provider archives to clients, advertise catch-up in guides, and monitor sessions in Stats\
✅ **Video on Demand** — Stream movies and TV series with rich metadata and IMDB/TMDB integration\
✅ **Multi-Format Output** — Export as M3U, XMLTV EPG, Xtream Codes API, or HDHomeRun device\
✅ **Real-Time Monitoring** — Live, VOD, and catch-up connection stats, bandwidth tracking, and automatic failover\
✅ **Stream Profiles** — Configure how Mino connects to backend streams (VLC, FFmpeg, Streamlink, or custom commands)\
✅ **Output Profiles** — Transcode what stream profiles deliver before it reaches the client (e.g. AC3 for media servers, AAC for browsers) with fMP4 or MPEG-TS container selection\
✅ **Multi-User & Access Control** — Granular permissions and network-based access restrictions\
✅ **Plugin System** — Extend functionality with custom plugins for automation and integrations\
✅ **Fully Self-Hosted** — Total control, no third-party dependencies

---

# Screenshots

<div align="center">
  <img src="docs/images/channels.png" alt="Channels" width="750"/>
  <img src="docs/images/guide.png" alt="TV Guide" width="750"/>
  <img src="docs/images/stats.png" alt="Stats & Monitoring" width="750"/>
  <img src="docs/images/m3u-epg-manager.png" alt="M3U & EPG Manager" width="750"/>
  <img src="docs/images/vod-library.png" alt="VOD Library" width="750"/>
  <img src="docs/images/settings.png" alt="Settings" width="750"/>
</div>

---

## 🛠️ Troubleshooting & Help

- **Something broken or unclear?** [Open an issue](https://github.com/D10Scot/Dispatcharr/issues)

---

## 🚀 Get Started in Minutes

### 🐳 Quick Start with Docker (Recommended)

```bash
docker pull ghcr.io/dispatcharr/dispatcharr:latest
docker run -d \
  -p 9191:9191 \
  --name dispatcharr \
  -v dispatcharr_data:/data \
  ghcr.io/dispatcharr/dispatcharr:latest
```

> Customize ports and volumes to fit your setup.

First-time web setup is limited to local/private networks by default. If you are installing on a VPS or otherwise reaching the UI from a public IP, either create the admin with `docker exec <container> python manage.py createsuperuser`, or set `DISPATCHARR_SETUP_ALLOWED_IP` to your client IP (see comments in the compose files). The setup page also shows the IP Mino sees.

Behind a reverse proxy, set `DISPATCHARR_TRUSTED_PROXIES` to your proxy's IP or CIDR so Network Access, Stats, and rate limits see real client IPs (defaults trust loopback peers only; use `none` to ignore forwarded headers).

**Upgrading:** before #182 the default also trusted private-network peers. A reverse proxy on a Docker or LAN network that has not set this variable now makes every client appear to be the proxy, so the default M3U/EPG network restriction admits public clients. Set it to the proxy's address, or to `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` to restore the old behaviour.

---

### 🐋 Docker Compose Options

| Use Case                    | File                                                    | Description                                                                                                   |
| --------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **All-in-One Deployment**   | [docker-compose.aio.yml](docker/docker-compose.aio.yml) | ⭐ Recommended! A simple, all-in-one solution — everything runs in a single container for quick setup.        |
| **Modular Deployment**      | [docker-compose.yml](docker/docker-compose.yml)         | Separate containers for Mino, Celery, Redis, and Postgres — perfect if you want more granular control. |
| **Development Environment** | [docker-compose.dev.yml](docker/docker-compose.dev.yml) | Developer-friendly setup with pre-configured ports and settings for contributing and testing.                 |

---

### 🛠️ Building from Source

> ⚠️ **Warning**: Not officially supported — but if you're here, you know what you're doing!

If you are running a Debian-based OS, use the `debian_install.sh` script. For other OS, contribute a script and we’ll add it!

---

## 🤝 Want to Contribute?

We welcome **PRs, issues, ideas, and suggestions**!

- Prior to contributing, please read the [CONTRIBUTING.md](CONTRIBUTING.md)

> Whether it's writing docs, squashing bugs, or building new features, your contribution matters! 🙋

---

## 📚 Documentation & Roadmap

**Upcoming Features (in no particular order):**

- 🎬 **VOD Management Enhancements** — Granular metadata control and cleanup of unwanted VOD content
- 📁 **Media Library** — Import local files and serve them over XC API
- 👥 **Enhanced User Management** — Customizable XC API output per user account
- 🔌 **Fallback Videos** — Automatic fallback content when channels are unavailable
- 📡 **HLS Output** — Live channels are served as HLS today (fMP4 segments, re-encoded for Apple devices, alongside MPEG-TS and fMP4); VOD, catch-up and recordings over HLS are still upcoming

---

## ❤️ Shoutouts

A huge thank you to all the incredible open-source projects and libraries that power Mino. We stand on the shoulders of giants!

---

## ✉️ Connect With Us

Have a question? Want to suggest a feature? Just want to say hi?\
➡️ **[Open an issue](https://github.com/D10Scot/Dispatcharr/issues)**.

---

## ⚖️ License & Legal

Mino is licensed under **GNU AGPL v3.0**: For full license details, see [LICENSE](https://www.gnu.org/licenses/agpl-3.0.html).

Mino is derived from [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) (AGPL-3.0).

---

### 🚀 _Happy Streaming! The Mino Team_
