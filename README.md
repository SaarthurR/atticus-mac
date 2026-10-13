<p align="center"><img src="docs/banner.png" alt="Atticus. Your whole Mac, one sentence away." width="100%"></p>

<p align="center">
  Hold <kbd>⌃ control</kbd> <kbd>⌥ option</kbd> <kbd>space</kbd>, say what you need, let go.<br>
  Atticus moves your windows, finds your files, reads your screen and gets it done.
</p>

<p align="center">
  <b>⚡ Fast</b> &nbsp;·&nbsp; <b>🔑 No API key</b> &nbsp;·&nbsp; <b>🧠 Remembers you</b> &nbsp;·&nbsp; <b>Free and open source</b>
</p>

- **Fast.** Simple asks skip the AI: an app opens in 0.08 s. Ask for an action once and Atticus learns it, so next time it runs in a blink, with no AI and for free.
- **No API key.** It runs on the Claude Pro or Max plan you already have, through Claude Code. Nothing to sign up for, no key to paste, no extra bill.
- **Remembers you.** Say "remember…" and every ask after that knows it. It picks up who you are (your name, your apps) and fixes its own mistakes when you correct it.

> **On Windows?** [@FindlayHi](https://github.com/FindlayHi) built **[Atticus for Windows](https://github.com/FindlayHi/atticus-windows)**, with integrations for Home Assistant, Jellyfin, Immich and more.

<p align="center">
  <img alt="macOS" src="https://img.shields.io/badge/macOS-1d1d1f?style=for-the-badge&logo=apple&logoColor=white">
  <img alt="Swift" src="https://img.shields.io/badge/Swift-1d1d1f?style=for-the-badge&logo=swift&logoColor=white">
  <img alt="Claude" src="https://img.shields.io/badge/Claude_Haiku-1d1d1f?style=for-the-badge&logo=anthropic&logoColor=white">
  <img alt="Cost" src="https://img.shields.io/badge/~0.18%C2%A2_per_ask-1d1d1f?style=for-the-badge">
</p>

<br>

https://github.com/user-attachments/assets/d697edcf-dc25-428b-bf50-470e41030952

<br>

## Just ask

| You say | Atticus |
|---|---|
| *"Code on my big screen, Chrome and Terminal on the laptop."* | Arranges three windows across two displays. |
| *"Open Spotify."* · *"Terminal on the left."* | Runs instantly, with no AI at all. |
| *"Find my notes about the Tokyo trip."* | Searches your files by what's inside them, opens the match on your other screen. |
| *"What's wrong with this code?"* | Looks at your screen and answers in a line. |
| *"Reply to this. Thursday works, send me a time."* | Reads the email on screen and writes the reply. Insert puts it at your cursor. It never sends. |
| *"Find me a desk lamp under $30 on Amazon."* | Works in Chrome behind your apps; a live mini screen shows it. |
| *"Where do I turn on Night Shift?"* | A ring lights up the exact spot on your screen (Show me where). |
| *"Summarize this article in three bullets."* | Reads the page for you. |
| *"Play my late night coding playlist on Spotify."* | Plays it in a second, no clicks. Any song, artist or playlist. |
| *"When I say focus mode, close Slack and open my to-do list."* | Remembers it. Next time, two words do it all. |

<p align="center"><img src="docs/demo.gif" alt="Atticus arranging windows across two screens" width="820"></p>

## Why Atticus

<table>
<tr>
<td width="33%" valign="top"><h3>Fast</h3>Opening apps and sites, moving windows, web searches and music skip the AI entirely (an app opens in 0.08 s). Actions you ask for once (opening apps, moving windows, playing music) become learned shortcuts: "Open Calculator and Chess" went from 5.5 s to 0.4 s, with no AI.</td>
<td width="33%" valign="top"><h3>No API key</h3>Runs on the Claude plan you already have, through <code>claude -p</code>. About 0.18¢ of plan usage per ask (~550 asks for $1 at API list rates). Atticus itself is free.</td>
<td width="33%" valign="top"><h3>Remembers you</h3>"Remember: open means bring it to the front." Saved rules go with every ask. It learns lasting facts about you (name, city, favorite apps), and when you correct it, it saves a rule so it gets it right next time. Edit all of it in Settings.</td>
</tr>
<tr>
<td valign="top"><h3>Private ears</h3>Apple's on-device speech turns your voice into text. Audio never leaves your Mac.</td>
<td valign="top"><h3>Your whole Mac</h3>Apps, windows, files, settings, the web and the screen, with native Accessibility controls for clicking, scrolling and typing inside apps.</td>
<td valign="top"><h3>Safe by default</h3>Safe mode runs the AI's commands in Claude Code's sandbox: they can only write to a scratch folder. Before anything deletes, sends, buys or changes a file, Atticus asks you first. <code>rm</code>, <code>sudo</code>, disk tools and shutdown are always blocked. Every exact command is in the ask log.</td>
</tr>
</table>

<details>
<summary><b>How the shortcut and the box work</b></summary>
<br>

Choose **Hold to talk** or **Press to toggle** in Settings → General → Shortcut behavior. Hold mode sends when you release. Toggle mode starts on the first press and sends on the second; pauses keep listening. Pressing the shortcut while Atticus answers stops it; during spoken playback it stops the voice. Esc cancels listening without sending. Toggle recordings reach a review screen after 60 seconds, rather than sending automatically. Closing the overlay or pausing Atticus stops its microphone, workers and voice.

Click any answer to copy it, including earlier answers still shown in the box. Click your request to edit and ask again, or press ↑ in an empty typing box to recall the latest request. The overlay stays within your display when resized and respects Reduce Motion. While Atticus works in a covered window, another Space, or another display, a live mini screen shows that window; the steps below show the action. The finished view stays until the next ask, typing, or a click on it. Click it to open that exact window. The preview stays on your Mac, is never sent to the AI or saved, and stops streaming when the task ends. Without Screen Recording permission, the same card shows the app icon and window title.

Apple's final transcript confirms each voice request before AI tools or learned shortcuts run. AI reasoning can start during a pause, but its tools wait for confirmation. If speech finalization takes too long, Atticus offers the partial text for review. Instant commands still skip the AI entirely. Supported built-in commands run mid-sentence, before you send, with Instant commands and Act while I’m talking on (Settings → Intelligence). Learned shortcuts wait for confirmed words.

</details>

## Meeting Copilot

Enable Meeting Copilot in Settings → Meetings → Meeting Copilot settings, then open it for a call or try the demo. Drag its header or empty background in any state; the minimized pill also drags. Positions and expanded sizes are remembered per display. Double-click the header to return to the default spot. Frames stay inside the display’s usable area, including after a display change.

**Save meeting transcripts** is on by default. While listening, a quiet indicator shows when saving is active. Text, speaker labels, timestamps, notes and copilot answers save incrementally under `$ATTICUS_DIR/meetings/<meeting-id>/` (normally `~/.config/atticus/meetings/`). Each folder is private (`0700`), with `metadata.json` and an append-only `events.jsonl` (`0600`). Unfinished speech is checkpointed every two seconds; interrupted calls remain readable. Audio is never saved.

Settings → **Meetings**, or **See all meetings** after a call, opens the local archive. Search titles and transcripts, use ↑/↓ and Return to browse, ⌘F to search and Esc to go back. Each meeting shows its recap, action items, notes, answers and timestamped transcript. Copy, export Markdown, or delete with confirmation. Turning saving off stops the current archive and asks whether to keep or delete past meetings.

With **AI meeting summaries** on (the default), Claude reads the transcript once after each ended session and writes a summary and action items, on your own Claude plan. Turn it off to keep transcripts entirely on your Mac; you still get a simpler local recap that quotes decisions and opening/closing speech. A failed AI recap leaves the local transcript intact. Resuming cancels a pending recap and the next End summarizes the full transcript. Closing or pausing stops recap work; already saved text stays on your Mac. Asking Atticus about a past meeting lets it search that archive with `--meeting-history "<keywords, weekday or YYYY-MM-DD>"`. Live question answering retains the selected Meeting Copilot answer policy.

## Feedback

Choose **Report Feedback…** in the menu bar, **Report feedback** in Settings, or say/type “report feedback” or “report a bug”. Review the exact text before opening a GitHub issue draft. It contains a short template, version/commit, macOS and Mac model, model, safe mode and input settings. **Include my last ask** starts off; answers, screen content and command logs are never attached. Submit the draft yourself on GitHub.

## Install

You need:
- **macOS 26** or later (Atticus uses Apple's new on-device speech)
- **A paid Claude plan** (Pro or Max) and [Claude Code](https://claude.com/claude-code). No Claude Code yet? The setup window installs it and signs you in.
- Apple's command line tools: `xcode-select --install`
- Accessibility permission enables native clicks, scrolling, menus, keys, dragging and field typing.

Paste this in Terminal:

```
curl -fsSL https://raw.githubusercontent.com/SaarthurR/atticus-mac/main/install.sh | bash
```

It checks your Mac, downloads Atticus to `~/.atticus`, builds `~/Applications/Atticus.app`, and opens it. Atticus starts at login and updates itself from there (turn that off in Settings → About & Updates).

### Nix

On macOS with Nix flakes enabled:

```bash
nix run github:SaarthurR/atticus-mac
```

The flake runs the standard installer, which keeps the writable clone Atticus uses for updates, so macOS 26+ and Apple's command line tools are still required. `nix profile add github:SaarthurR/atticus-mac` installs an `atticus` launcher; run it to install or update the app.

Working on the code instead? Clone the repo anywhere and run `./build.sh` after each change. A Devbox environment is included for Python regression tests; run `devbox shell`, then `devbox run test`.

The first launch opens a setup window. It checks your Claude plan, then asks for each macOS permission.
After that, Atticus lives in the menu bar. Open it from Spotlight (⌘Space, "Atticus") for Settings: shortcut, sounds, model, speed, screen, memory and usage.
If you sign out of Claude later, the setup window comes back by itself.
To see it again: `defaults delete com.atticus.app onboarded`, then restart the app.

Test: `python3 atticus.py --selftest` on macOS, plus `python3 -m unittest discover -s tests -v` for offline regressions. After building, `~/Applications/Atticus.app/Contents/MacOS/Atticus --selftest` checks native transcript matching without opening the app. Node, when installed, also checks embedded JavaScript syntax. For the UI interaction checks, run `python3 -m http.server 8765 --bind 127.0.0.1` from the repo and open `http://127.0.0.1:8765/tests/ui.html`; it uses a mock native bridge and makes no Mac actions or AI calls.

Remove: `launchctl bootout gui/$(id -u)/com.atticus.app`, then delete `~/Applications/Atticus.app`, `~/.atticus`, `~/.config/atticus` (your settings and history) and `~/Library/LaunchAgents/com.atticus.app.plist`.

## Watch for me

Say "tell me when Codex is done" or "watch this page until it says shipped". Atticus sets it up once, then checks every 5 seconds on your Mac with no AI, so waiting is free. When it fires you get a notification, and it runs a follow-up if you asked for one. A window must stay open on this desktop (covered is fine). Coding agents like Codex are watched through their own log, with no screen at all. Say "stop watching" to cancel.

## Budget

Atticus has to stay fast and nearly free, so new features must fit under these limits:

- Instant commands: no AI, $0.
- AI asks: median under $0.002 and 6 s over the last 50 (Oct 10, 2026: $0.00095, 5.0 s). Check with `python3 atticus.py --budget`.
- System prompt: under 10,000 characters with every option on. Every ask pays for it, and a test enforces it.
- Anything that waits or runs in the background: $0 while it waits. AI only to set it up and to act at the end.

## Usage count

Once a day, Atticus sends one random ID (made on your Mac, not tied to you) to PostHog, so I can see how many people use it. It never sends your name, your asks or your screen. Turn it off in Settings → Account & Access → Count me as a user.

If you say yes to **Help improve Atticus** (asked once, off until you do), a task that fails sends what you asked, the steps Atticus took and why it failed, under the same random ID. Emails, numbers, file paths, link details and anything typed for you are removed on your Mac first. Turn it off in Settings → Account & Access → Help improve Atticus.

## Files

- `Atticus.swift`: the app (hotkey, speech, overlay, onboarding window)
- `atticus.py`: the brain (fast commands, system prompt, helpers for windows, web and screen)
- `ui/ui.html`, `ui/onboarding.html`, `ui/settings.html`: the overlay, the welcome flow, and Settings
- `ui/AppIcon.icns`: the app icon
- `ui/orbs.js`: the [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs) engine (MIT, Jakub Antalik)

## License

MIT. See `LICENSE`. `ui/orbs.js` is from [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs), also MIT.

## Contributing

Run regressions with a scratch `ATTICUS_DIR` and use `tests/ui.html` and `tests/settings.html` for mock-bridge UI checks. Keep personal agent settings, credentials and runtime state out of commits. Anonymous usage telemetry uses a public PostHog capture token. Set `ATTICUS_POSTHOG_KEY` to override it (an empty value disables telemetry), or turn off Count me as a user in Settings.

Hands: ideas and some logic adapted from Plip (github.com/hussainn7/plip-oss, MIT).
