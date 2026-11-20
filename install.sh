#!/bin/bash
# Atticus installer. Paste in Terminal:
#   curl -fsSL https://raw.githubusercontent.com/SaarthurR/atticus-mac/main/install.sh | bash
# Downloads the source to ~/.atticus (Atticus updates itself from there), builds the app, opens it.
set -e
DIR="${ATTICUS_DIR:-$HOME/.atticus}"
echo "Installing Atticus…"
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Atticus needs macOS 26 or later."; exit 1; }
if ! xcode-select -p >/dev/null 2>&1; then
  echo "First, Apple's command line tools. A macOS window will open: click Install."
  echo "When it finishes, paste the install line again."
  xcode-select --install 2>/dev/null || true
  exit 1
fi
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q --ff-only || { echo "Could not update $DIR. Delete that folder, then paste the install line again."; exit 1; }
else
  git clone -q --depth 1 https://github.com/SaarthurR/atticus-mac.git "$DIR"
fi
"$DIR/build.sh"
echo "Done. The Atticus setup window walks you through the rest."
