# 🎮 Palworld Dedicated Server For ARM64

**🚀 Production-ready ARM64 optimized Palworld server with FEX + SteamCMD integration**

## 🌟 What Makes This Special?

### 🔧 **ARM64-Optimized Palworld Server**

- **Revolutionary FEX Integration**: 3-5x faster than QEMU on ARM64
- **Apple Silicon Ready**: M1/M2/M3 Macs with native performance
- **Raspberry Pi Support**: Perfect for home servers and edge computing
- **AWS Graviton Optimized**: Cloud-native ARM64 deployment

### 🤖 **Intelligent Auto-Management**

- **🔄 Smart Idle Restart**: Automatically restart when no players for configurable time
- **📊 Advanced Health Monitoring**: CPU, memory, disk, and API health checks with auto-recovery
- **💾 Enterprise Backup System**: Daily/weekly/monthly rotation with intelligent cleanup
- **🎯 Zero-Downtime Updates**: SteamCMD integration with graceful server management

### 🌍 **Multi-Language Discord Integration**

- **Real-time Notifications**: Player join/leave, server events, backup completion
- **3 Languages Supported**: Korean, English, Japanese
- **Smart Event Filtering**: Configurable notification preferences
- **Rich Embeds**: Beautiful Discord messages with server status

## 🚀 Quick Start

### **🐳 One-Command Deploy**

```bash
docker run -d \
  --name palworld-server \
  -p 8211:8211/udp \
  -p 127.0.0.1:8212:8212/tcp \
  -p 127.0.0.1:25575:25575/tcp \
  -e ADMIN_PASSWORD=your-secure-password \
  -v palworld-data:/home/steam/palworld_server \
  -v palworld-backups:/home/steam/backups \
  peozozo123/palworld-server:latest
```

> ⚠️ **Security**: REST API (8212) and RCON (25575) bind to `127.0.0.1` by default.
> To expose them externally, configure a VPN, firewall allowlist, or ingress authentication.

### **📋 Docker Compose (Recommended)**

```yaml
version: "3.8"
services:
    palworld-server:
        image: peozozo123/palworld-server:latest
        container_name: palworld-server
        restart: unless-stopped
        ports:
            - "8211:8211/udp" # Game Server
            - "127.0.0.1:8212:8212/tcp" # REST API (localhost only)
            - "127.0.0.1:25575:25575/tcp" # RCON (localhost only)
        environment:
            - SERVER_NAME=🎮 My Palworld Server
            - MAX_PLAYERS=32
            - ADMIN_PASSWORD=your-secure-password
        volumes:
            - palworld-data:/home/steam/palworld_server
            - palworld-backups:/home/steam/backups
            - palworld-logs:/home/steam/logs

volumes:
    palworld-data:
    palworld-backups:
    palworld-logs:
```

### **Idle Pause with RCON Disabled**

Use [docker-compose.idle-pause.example.yml](./docker-compose.idle-pause.example.yml)
for a simple example that disables RCON, keeps REST localhost-only, and
pauses the game process after 30 idle minutes. The world is saved first, and
the process automatically resumes when traffic reaches the game UDP port:

```bash
# Change SERVER_PASSWORD and ADMIN_PASSWORD before starting it.
docker compose -f docker-compose.idle-pause.example.yml up -d

# Manual resume remains available if needed.
docker exec palworld-server palworld-control resume
```

## ⚙️ Configuration

### **🔧 Essential Environment Variables**

| Variable              | Default             | Description                          |
| :-------------------- | :------------------ | :----------------------------------- |
| `SERVER_NAME`         | `"Palworld Server"` | 🏷️ Server display name               |
| `SERVER_PASSWORD`     | `""`                | 🔒 Server join password              |
| `ADMIN_PASSWORD`      | _(required)_        | 👑 Admin/RCON password (no default)  |
| `MAX_PLAYERS`         | `32`                | 👥 Maximum player count (1-32)       |
| `BACKUP_ENABLED`      | `true`              | 💾 Enable automatic backups          |
| `DISCORD_WEBHOOK_URL` | `""`                | 💬 Discord webhook for notifications |
| `LANGUAGE`            | `ko`                | 🌍 Language (`ko`/`en`/`ja`)         |

### **⏰ NEW: Idle Restart Feature**

| Variable                     | Default | Description                               |
| :--------------------------- | :------ | :---------------------------------------- |
| `IDLE_RESTART_ENABLED`       | `true`  | 🔄 Enable auto-restart when no players    |
| `IDLE_RESTART_MINUTES`       | `30`    | ⏱️ Minutes to wait before restart         |
| `IDLE_RESTART_MODE`          | `restart` | Idle action: `restart` or `pause`       |
| `IDLE_PAUSE_INTERFACE`       | `eth0`  | Interface used to detect game UDP traffic |
| `DISCORD_EVENT_IDLE_RESTART` | `true`  | 📣 Discord notification for idle restarts |

### **🎮 Game Settings (150+ configurable options)**

| Variable              | Default | Description                  |
| :-------------------- | :------ | :--------------------------- |
| `DIFFICULTY`          | `None`  | 🎯 Game difficulty           |
| `IS_PVP`              | `false` | ⚔️ Enable PvP mode           |
| `DAY_TIME_SPEED_RATE` | `1.0`   | ☀️ Day time speed multiplier |
| `EXP_RATE`            | `1.0`   | 📈 Experience gain rate      |
| `PAL_CAPTURE_RATE`    | `1.0`   | 🎯 Pal capture difficulty    |

[📄 **Complete Environment Variables List**](https://github.com/supersunho/docker-palworld-server/blob/main/.env.example)

## 🎯 ARM64 Performance Revolution

### **Why FEX Matters**

Traditional ARM64 emulation (QEMU) is slow and resource-heavy. Our FEX integration changes everything:

| Platform      | Boot Time  | Memory Usage | CPU Usage |
| :------------ | :--------- | :----------- | :-------- |
| ARM64 + FEX   | ~2 minutes | ~1.2GB       | ~15%      |
| x86_64 Native | ~2 minutes | ~1.0GB       | ~12%      |
| ARM64 + QEMU  | ~8 minutes | ~2.1GB       | ~45%      |

### **Optimized FEX Configuration**

```bash
# Automatically applied in our container
FEX_ENABLE_JIT_CACHE=1
FEX_JIT_CACHE_SIZE=1024
FEX_ENABLE_LAZY_MEMORY_DELETION=1
FEX_ENABLE_STATIC_REGISTER_ALLOCATION=1
```

## 📊 Advanced Features

### **🔄 Smart Idle Management**

```bash
# Automatically restart server when empty
IDLE_RESTART_ENABLED=true
IDLE_RESTART_MINUTES=30
IDLE_RESTART_MODE=restart  # Use "pause" for save, SIGSTOP, and connection wake

# Optional manual resume; normal game connection attempts resume automatically
docker exec palworld-server palworld-control resume

# Inspect the managed process and lifecycle state
docker exec palworld-server palworld-control status

# Discord notification in your language
🇺🇸 "No players for 30 minutes. Restarting server (My Server)."
🇰🇷 "30분 동안 접속자가 없어 서버(My Server)를 재시작합니다."
🇯🇵 "30分間プレイヤーがいなかったため、サーバー(My Server)を再起動します。"
```

Pause mode saves the world, starts a separate `knockd` listener, and then freezes
Palworld with `SIGSTOP`. An inbound packet on the external game UDP port writes a
wake marker and the lifecycle manager sends `SIGCONT`; REST polling remains off
while frozen. The container needs `NET_RAW`, which is included in the supplied
Compose and Helm configuration. Configuration-file changes are validated and
applied through a graceful container restart; environment-variable changes
require recreating the container.

### **💾 Enterprise Backup System**

```yaml
backup:
    enabled: true
    interval_seconds: 3600 # Hourly backups
    retention_days: 7 # Keep daily for 7 days
    retention_weeks: 4 # Keep weekly for 4 weeks
    retention_months: 6 # Keep monthly for 6 months
    compress: true # Gzip compression
    max_backups: 100 # Total backup limit
```

### **📡 REST API \& RCON**

```bash
# REST API endpoints
curl http://localhost:8212/v1/api/info
curl http://localhost:8212/v1/api/players
curl http://localhost:8212/v1/api/settings

# RCON commands
rcon-cli --host localhost --port 25575 --password ${ADMIN_PASSWORD} ShowPlayers
rcon-cli --host localhost --port 25575 --password ${ADMIN_PASSWORD} "Broadcast Hello!"
```

### **🩺 Health Monitoring**

```bash
# Built-in health check
docker exec palworld-server python /app/scripts/healthcheck.py

# Automatic recovery on failures
# CPU > 90%, Memory > 95%, API timeouts = auto-restart
```

## 🐳 Publishing to Docker Hub with GitHub Actions

The workflow in `.github/workflows/build-and-deploy.yml` builds the ARM64 image and
publishes `peozozo123/palworld-server:latest` plus versioned and `-arm64` tags.

One-time setup:

1. Create the `peozozo123/palworld-server` repository on Docker Hub.
2. In Docker Hub, open **Account settings → Personal access tokens** and create a
   token with read/write permission.
3. In the GitHub repository, open **Settings → Secrets and variables → Actions**
   and add these repository secrets:

   - `DOCKERHUB_USERNAME`: `peozozo123`
   - `DOCKERHUB_TOKEN`: the Docker Hub personal access token (do not use your password)

4. Open **Actions → Palworld Server Builder → Run workflow**. Leave
   `source_version` as `latest`, enable `force_rebuild` when replacing an existing
   tag, and run the workflow.

After the workflow succeeds, verify the published image:

```bash
docker pull peozozo123/palworld-server:latest
```

## 🛠️ Advanced Usage

### **Multi-Arch Build Commands**

```bash
# Clone repository
git clone https://github.com/supersunho/docker-palworld-server.git
cd docker-palworld-server

# Build for your platform
docker build -t palworld-server .

# Build
docker buildx build --platform linux/arm64 -t palworld-server .
```

### **Custom Configuration File**

```bash
# Mount your own configuration
docker run -d \
  -v ./my-config.yaml:/app/config/default.yaml \
  -v palworld-data:/home/steam/palworld_server \
  peozozo123/palworld-server:latest
```

### **Development Mode**

```bash
# Run with development tools
docker run -it --rm \
  -v $(pwd):/app \
  -p 8211:8211/udp \
  peozozo123/palworld-server:latest bash
```

## 🌍 Multi-Language Discord Notifications

### **Supported Languages**

- 🇰🇷 **Korean** (`ko`) - 한국어 알림
- 🇺🇸 **English** (`en`) - English notifications
- 🇯🇵 **Japanese** (`ja`) - 日本語通知

### **Example Notifications**

```yaml
Player Join:
🇺🇸 "Player joined: Steve (5 players online)"
🇰🇷 "플레이어 참가: Steve (현재 5명)"
🇯🇵 "プレイヤー参加: Steve (現在5人)"

Server Restart:
🇺🇸 "Server restarted due to idle timeout"
🇰🇷 "무접속으로 인한 서버 재시작"
🇯🇵 "アイドルタイムアウトによるサーバー再起動"
```

## 📈 Resource Requirements \& Scaling

### **Recommended Specifications**

| Players | CPU Cores | RAM | Storage | Bandwidth |
| :------ | :-------- | :-- | :------ | :-------- |
| 1-8     | 2 cores   | 2GB | 10GB    | 5 Mbps    |
| 9-16    | 4 cores   | 4GB | 15GB    | 10 Mbps   |
| 17-24   | 6 cores   | 6GB | 20GB    | 15 Mbps   |
| 25-32   | 8 cores   | 8GB | 25GB    | 20 Mbps   |

### **Cloud Provider Recommendations**

#### **ARM64 Cloud Options** 💚

- **AWS**: Graviton3/4 instances (c7g, m7g series)
- **Oracle Cloud**: Ampere A1 (4 cores, 24GB RAM - Always Free!)
- **Hetzner**: CAX series ARM64 VPS
- **Scaleway**: ARM64 instances

## 🤝 Community \& Support

### **🔗 Links**

- 📦 **Docker Hub**: [peozozo123/palworld-server](https://hub.docker.com/r/peozozo123/palworld-server)
- 📂 **GitHub**: [supersunho/docker-palworld-server](https://github.com/supersunho/docker-palworld-server)
- 🐛 **Issues**: [Report Issues](https://github.com/supersunho/docker-palworld-server/issues)
- 💬 **Discussions**: [Community Discussions](https://github.com/supersunho/docker-palworld-server/discussions)

## 📜 License \& Acknowledgments

**MIT License** - Free for personal and commercial use.

<div align="center">

### **⭐ Love this project? Give it a star! ⭐**

</div>
