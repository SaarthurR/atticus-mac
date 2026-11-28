#!/bin/bash
# Installs Atticus: builds Atticus.app, starts it at login, and (re)starts it now. Run it again after any change.
set -e; cd "$(dirname "$0")"
# Stable failure codes let the updater report the step without sending build output.
FAILURE=60   # prepare
STAGE=
trap 'result=$?; [ -z "$STAGE" ] || rm -rf "$STAGE"; [ "$result" -eq 0 ] || exit "$FAILURE"' EXIT
VERSION=$(tr -d '\n' < VERSION)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION"; exit 1; }
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
(( VERSION_MINOR < 1000 && VERSION_PATCH < 1000 )) || { echo "VERSION components must be below 1000"; exit 1; }
BUILD=$((VERSION_MAJOR * 1000000 + VERSION_MINOR * 1000 + VERSION_PATCH))
COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Atticus needs macOS 26 or later (it uses Apple's new on-device speech)."; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Needs Apple's command line tools. Run: xcode-select --install   then run ./build.sh again."; exit 1; }
command -v python3 >/dev/null || { echo "Atticus needs Python 3. Install it, then run ./build.sh again."; exit 1; }
command -v claude >/dev/null || [ -x ~/.local/bin/claude ] || echo "Note: Claude Code is not installed yet. Atticus's setup window can install it, or you can pick Devin or Pi."
STAGE=$(mktemp -d)
# A compiler error must leave the installed app and its resources alone.
FAILURE=61   # compile
swiftc -O -target "$(uname -m)-apple-macos26.0" Atticus.swift -o "$STAGE/Atticus"
FAILURE=64   # package
APP="$STAGE/Atticus.app"   # stage resources and signing before replacing the installed app
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp atticus.py "$APP/Contents/Resources/"
cp ui/*.html ui/*.js ui/*.css "$APP/Contents/Resources/ui/"
cp ui/AppIcon.icns "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.atticus.app</string>
<key>CFBundleName</key><string>Atticus</string>
<key>CFBundleExecutable</key><string>Atticus</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>AtticusCommit</key><string>$COMMIT</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>AtticusSource</key><string>$(pwd)</string>
<key>LSUIElement</key><true/>
<key>NSMicrophoneUsageDescription</key><string>Atticus listens when you use its shortcut or microphone button.</string>
<key>NSAppleEventsUsageDescription</key><string>Atticus controls apps like Finder, Chrome and Music when you ask it to.</string>
<key>NSCalendarsFullAccessUsageDescription</key><string>Atticus reads your calendar, adds events you request, and asks before moving or deleting existing events. Calendar details are sent to your chosen AI model.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Atticus turns your words into text on this Mac.</string>
</dict></plist>
P
mv "$STAGE/Atticus" "$APP/Contents/MacOS/Atticus"
# With a code-signing identity named "Atticus Local Signing" in the keychain, macOS keeps permissions across
# rebuilds and auto-updates; ad hoc signing would ask for every permission again after each one. So make it once.
# codesign may use a key without a password prompt only if the key's partition list has "apple:", and setting that needs
# the keychain's password. A prompt hangs or fails every background update, so the key lives in Atticus's own keychain,
# whose password this script knows. A login-keychain key from older builds stays only if it already allows codesign.
FAILURE=62   # sign
KC=~/Library/Keychains/atticus-signing.keychain-db
identity() { security find-identity -p codesigning "$@" | awk '/Atticus Local Signing/{print $2; exit}'; }
ID=
[ -e "$KC" ] || { ID=$(identity); [ -z "$ID" ] || security dump-keychain -a 2>/dev/null |
  awk '/^keychain:/{k=0} /description: a\.p12$/{k=1} k && /description: (.*, )?apple:/{f=1} END{exit !f}' || ID=; }
if [ -z "$ID" ]; then
  if [ ! -e "$KC" ]; then
    K=$(mktemp -d)
    /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -subj "/CN=Atticus Local Signing" -addext "extendedKeyUsage=critical,codeSigning" \
      -addext "keyUsage=critical,digitalSignature" -keyout "$K/k.pem" -out "$K/c.pem" 2>/dev/null &&
    /usr/bin/openssl pkcs12 -export -inkey "$K/k.pem" -in "$K/c.pem" -out "$K/a.p12" -passout pass:atticus 2>/dev/null &&
    security create-keychain -p atticus "$KC" && security set-keychain-settings "$KC" &&
    security import "$K/a.p12" -k "$KC" -P atticus -T /usr/bin/codesign >/dev/null 2>&1 &&
    security set-key-partition-list -S apple-tool:,apple: -s -k atticus "$KC" >/dev/null 2>&1 ||
      { security delete-keychain "$KC" 2>/dev/null; true; }   # fails quietly: ad hoc still works
    rm -rf "$K"
  fi
  if [ -e "$KC" ]; then
    security unlock-keychain -p atticus "$KC"   # it locks again at every restart
    security list-keychains -d user | grep -q atticus-signing || security list-keychains -d user | xargs security list-keychains -d user -s "$KC"
    ID=$(identity "$KC")
  fi
fi
codesign -s "${ID:--}" --force "$APP"
FAILURE=63   # install
DEST=~/Applications/Atticus.app
mkdir -p "$(dirname "$DEST")"
[ ! -e "$DEST" ] || mv "$DEST" "$STAGE/previous.app"
if ! mv "$APP" "$DEST"; then
  [ ! -e "$STAGE/previous.app" ] || mv "$STAGE/previous.app" "$DEST"
  exit 1
fi
APP="$DEST"
# register with macOS, or System Settings can't list it for permissions
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
AGENT=~/Library/LaunchAgents/com.atticus.app.plist   # starts at login, restarts if it crashes (Quit stays quit)
mkdir -p ~/Library/LaunchAgents ~/.config/atticus
cat > "$AGENT" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.atticus.app</string>
<key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Atticus</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>StandardErrorPath</key><string>$HOME/.config/atticus/app.err</string>
</dict></plist>
P
[ -n "$ATTICUS_NO_RESTART" ] && exit 0   # the app's own updater restarts it when idle
# Reload the job so launchd refreshes its executable signing requirement after a rebuild.
launchctl bootout gui/$(id -u)/com.atticus.app 2>/dev/null || true
pkill -f "$APP/Contents/MacOS/Atticus$" 2>/dev/null && sleep 1   # stop a copy opened by hand too
# bootout can return before the job has finished unloading.
launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || { sleep 1; launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || {
  echo "Could not add Atticus to Login Items; opening it directly instead."
  open "$APP"
}; }
echo "Atticus is running. Hold Control+Option+Space and talk."
