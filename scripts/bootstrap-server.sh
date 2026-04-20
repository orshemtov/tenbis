#!/usr/bin/env bash
# bootstrap-server.sh — one-time setup on a fresh Linux server
# Run as your normal user (sudo is used only where required).
#
# Usage:
#   cd ~/tenbis
#   bash scripts/bootstrap-server.sh

set -euo pipefail

echo "==> Installing Chromium system dependencies (needs sudo)..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2t64 libpango-1.0-0 libpangocairo-1.0-0 \
    fonts-dejavu-core curl git

echo "==> Installing mise (if not already installed)..."
if ! command -v mise &>/dev/null; then
    curl https://mise.run | sh
    # Add mise to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"
    # Persist for future sessions
    shell_rc="$HOME/.bashrc"
    if [[ "$SHELL" == */zsh ]]; then
        shell_rc="$HOME/.zshrc"
    fi
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$shell_rc"
    echo 'eval "$(mise activate bash)"' >> "$shell_rc"
    eval "$(mise activate bash)"
else
    echo "    mise already installed: $(mise --version)"
fi

echo "==> Trusting mise config..."
mise trust

echo "==> Installing Python + uv via mise..."
mise install

echo "==> Installing Python dependencies..."
mise run install

echo ""
echo "Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  1. Copy your .env:           cp .env.example .env && \$EDITOR .env"
echo "  2. Sync browser profiles:    (on your laptop) mise run sync:profiles"
echo "  3. Install systemd timer:    mise run server:install"
echo "  4. Check timer is active:    mise run server:status"
echo "  5. Trigger a test run:       mise run server:run-now"
echo "  6. Watch the logs:           mise run server:logs"
