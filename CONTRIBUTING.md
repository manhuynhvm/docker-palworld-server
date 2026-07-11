# Contributing to Palworld Dedicated Server

Thank you for your interest in contributing! This project provides a
Palworld dedicated server with FEX emulation for ARM64.

## Development Setup

### Prerequisites

- Docker
- Python 3.11+
- Make (optional)

### Local Development

```bash
# Clone the repository
git clone https://github.com/supersunho/docker-palworld-server.git
cd docker-palworld-server

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov black flake8 mypy

# Run tests
pytest

# Run tests with coverage
pytest --cov=src
```

### Docker Build

```bash
# Build the image
docker build -t palworld-server:dev .

# Run the container
docker run -d --name palworld-dev \
  -p 8211:8211/udp \
  -p 8212:8212/tcp \
  -e ADMIN_PASSWORD=<your-password> \
  palworld-server:dev
```

## Project Structure

```
.
├── charts/                  # Helm chart for Kubernetes
├── config/                  # Default configuration files
├── docker/                  # Docker-related files
│   ├── entrypoint.sh        # Container entrypoint
│   ├── grafana/             # Grafana dashboard provisioning
│   ├── prometheus/          # Prometheus configuration
│   └── supervisor/          # Supervisor configuration
├── scripts/                 # Utility scripts
├── src/                     # Python source code
│   ├── backup/              # Backup manager
│   ├── clients/             # API/RCON clients
│   ├── config/              # Configuration classes
│   ├── managers/            # Business logic managers
│   ├── monitoring/          # Monitoring system
│   ├── notifications/       # Discord notifications
│   ├── protocols/           # Abstract interfaces
│   └── utils/               # Utilities
└── tests/                   # Test suite (pytest)
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run the test suite: `pytest`
5. Ensure all tests pass
6. Submit a pull request

### Commit Guidelines

- Use conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`
- Keep commits focused on a single change
- Reference issues where applicable

## Code Style

- Follow PEP 8
- Use type hints for all function signatures
- Write docstrings for public interfaces
- Keep functions focused and single-purpose

## Testing

- All new features should include tests
- Run `pytest` before submitting a PR
- Aim for >80% coverage on new code

## Questions?

Open an issue for questions or discussions.
