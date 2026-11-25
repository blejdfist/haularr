![Haularr](frontend/src/lib/assets/logo.png)

[![CI](https://github.com/blejdfist/haularr/actions/workflows/ci.yml/badge.svg)](https://github.com/blejdfist/haularr/actions/workflows/ci.yml)

Haularr is a download orchestrator for self-hosted media automation. It connects sources to libraries, managing the journey from download discovery through file transfer, processing, and library import in one single web interface.

## Features

- **Automate your download workflow**: Discover downloads, transfer files, verify and extract media, and coordinate library imports.
- **Organize multiple sources**: Route downloads to the right folders and libraries using tag mappings.
- **Monitor everything in one place**: Manage connections, follow job progress, and investigate issues through the web interface.
- **Keep transfers moving**: Resume interrupted transfers and recover unfinished jobs after a restart.
- **Run on your own infrastructure**: Deploy with Docker and keep your configuration and files in persistent storage.

## Supported sources

- **[rTorrent](https://github.com/rakshasa/rtorrent)**: Discover and track downloads across one or more instances, with FTP/FTPS transfers to local storage.

## Supported libraries

- **[Sonarr](https://sonarr.tv/)**: Import TV episodes into your series library.
- **[Radarr](https://radarr.video/)**: Import movies into your movie library.

## Getting started

### Use the published Docker image

Run Haularr with persistent configuration and directories for temporary and completed files:

```bash
docker run -d \
  --name haularr \
  --restart unless-stopped \
  -p 8080:8080 \
  -v haularr-config:/config \
  -v /path/to/staging:/data/staging \
  -v /path/to/completed:/data/completed \
  ghcr.io/blejdfist/haularr:latest
```

Replace the host paths with your own directories. Share the completed directory with Sonarr/Radarr and configure matching import paths.

### Build your own image

Clone the repository and build from its root:

```bash
git clone https://github.com/blejdfist/haularr.git
cd haularr
docker build -t haularr:local .
```

Run it with the command above, replacing `ghcr.io/blejdfist/haularr:latest` with `haularr:local`.

Open [http://localhost:8080](http://localhost:8080), create your admin account, and configure your sources and Sonarr/Radarr libraries.

## CLI reference

```text
haularr [-h] [--reload]
```

| Command | Description |
| --- | --- |
| `haularr` | Start the server (default: `0.0.0.0:8080`). |
| `haularr --reload` | Restart automatically when backend code changes during development. |
| `haularr -h`, `haularr --help` | Show command-line help. |

From a source checkout with dependencies installed, use `uv run haularr`.

## Configuration

Configure the server through `HAULARR_*` environment variables or a `.env` file:

| Variable | Default | Purpose |
| --- | --- | --- |
| `HAULARR_HOST` | `0.0.0.0` | Address to listen on. |
| `HAULARR_PORT` | `8080` | HTTP port. |
| `HAULARR_CONFIG_DIR` | `/config` | Directory for the database, keys, and logs. |
| `HAULARR_LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |

See [.env.example](.env.example) for more settings.

## License

Haularr is licensed under the [GNU General Public License v3.0](LICENSE).
