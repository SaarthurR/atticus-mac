<p align="center"><img src="docs/banner.png" alt="Atticus. Your whole Mac, one sentence away." width="100%"></p>

<p align="center">
  Hold <kbd>⌃ control</kbd> <kbd>⌥ option</kbd> <kbd>space</kbd>, say what you need, let go.<br>
  Atticus moves your windows, finds your files, reads your screen and gets it done.
</p>

<p align="center"><a href="https://ko-fi.com/saarthr"><b>☕ Leave a tip</b></a> · Atticus is free; tips keep it going.</p>

<p align="center">
  <b>🧠 Learns as you use it</b> &nbsp;·&nbsp; <b>⚡ Fast</b> &nbsp;·&nbsp; <b>🔑 No API key</b> &nbsp;·&nbsp; <b>Free and open source</b>
</p>

## Quick install

```
curl -fsSL https://raw.githubusercontent.com/SaarthurR/atticus-mac/main/install.sh | bash
```

Needs macOS 26 and an AI client: Claude Code on a Claude plan, Devin, Pi or a local model. [Full install steps](#install)

## What it does

- **Learns.** Ask for something new once and it works out the steps. Ask again and it runs in a blink, with no AI.
- **Instant commands.** Opens apps, moves windows, plays music and searches the web with no AI at all.
- **Sees your screen.** Ask about anything on screen. Ask "where do I click?" and it points at the spot.
- **Draws to explain.** "Explain this and draw it" builds a labeled diagram on your screen.
- **Dictate anywhere.** Hold fn, talk, let go. Your words land in any text field, cleaned up.
- **Hands-free.** Turn on Settings → General → Wake word, then just say "Atticus" (or any wake word you pick). Keep talking after each answer; the box stays up while you work and only ✕ closes it.
- **Background agents.** Big jobs run behind your apps while you keep working.
- **Meeting Copilot.** Answers and notes during calls, saved on your Mac.
- **Remembers you.** Say "remember…" and every ask after that knows it.
- **Your plan, no API key.** Runs on Claude, Devin, Pi or a local model.
- **Private and safe.** Your voice stays on your Mac. Deletes, sends and purchases ask first.

> **On Windows?** [@FindlayHi](https://github.com/FindlayHi) built **[Atticus for Windows](https://github.com/FindlayHi/atticus-windows)**, with integrations for Home Assistant, Jellyfin, Immich and more.

<p align="center">
  <img alt="macOS" src="https://img.shields.io/badge/macOS-1d1d1f?style=for-the-badge&logo=apple&logoColor=white">
  <img alt="Swift" src="https://img.shields.io/badge/Swift-1d1d1f?style=for-the-badge&logo=swift&logoColor=white">
  <img alt="Claude" src="https://img.shields.io/badge/Claude_Haiku-1d1d1f?style=for-the-badge&logo=anthropic&logoColor=white">
  <img alt="Cost" src="https://img.shields.io/badge/~0.18%C2%A2_per_ask-1d1d1f?style=for-the-badge">
  <a href="https://ko-fi.com/saarthr"><img alt="Support on Ko-fi" src="https://img.shields.io/badge/Support_on_Ko--fi-1d1d1f?style=for-the-badge&logo=kofi&logoColor=white"></a>
</p>

<br>

https://github.com/user-attachments/assets/26822ad2-6281-477d-b676-2f490a4a207b

<br>

## Just ask

| You say | Atticus |
|---|---|
| *"Code on my big screen, Chrome and Terminal on the laptop."* | Arranges three windows across two displays. |
| *"Open Spotify."* · *"Terminal on the left."* | Runs instantly, with no AI at all. |
| *"Find my notes about the Tokyo trip."* | Searches your files by what's inside them, opens the match on your other screen. |
| *"What's wrong with this code?"* | Looks at your screen and answers in a line. |
| *"Reply to this. Thursday works, send me a time."* | Reads the email on screen and writes the reply. Insert puts it at your cursor. It never sends. |
| *"Move my dentist appointment to 4."* | Shows the old and new time on a card and moves it when you approve. Adding is immediate; moving or deleting asks first. |
| *"Tell the agent in my terminal to also run the tests."* | Types it into that window in the background while you keep working. If it can't confirm the send, it leaves the text there and asks for the window. |
| *"Find me a desk lamp under $30 on Amazon."* | Works in Chrome behind your apps; a live mini screen shows it. |
| *"Where do I turn on Night Shift?"* | A ring lights up the exact spot on your screen (Show me where). |
| *"Summarize this article in three bullets."* | Reads the page for you. |
| *"Play my late night coding playlist on Spotify."* | Plays it in a second, no clicks. Any song, artist or playlist. |
| *"When I say focus mode, close Slack and open my to-do list."* | Remembers it. Next time, two words do it all. |

<p align="center"><img src="docs/demo.gif" alt="Atticus arranging windows across two screens" width="820"></p>

## Hands-free

Turn on **Wake word** in Settings → General (off by default). The word is "Atticus" unless you type your own beside the switch. Say it, with or without "hey" first, wait for Listening…, then ask. Speech is recognized on your Mac only. After each answer it listens again quietly, with a small "Listening..." beside the timer; start talking and your words fill the bubble. Clicking other apps never closes a hands-free chat, so you can keep working while it does things for you. ✕ or Esc ends it, and a chat nobody talks to fades after about 90 seconds unless you moved or resized the box. The hotkey always takes over. While the wake word is on, macOS shows the orange mic dot.

While Atticus works, the line next to ✕ minimizes the box to a small bar with its live steps. Hover and click the line to bring it back.

## Safe by default

Safe mode runs the AI's commands in Claude Code's sandbox, so they can only write to a scratch folder. Before anything deletes, sends, buys or changes a file, Atticus asks you first. <code>rm</code>, <code>sudo</code>, disk tools and shutdown are always blocked. Every exact command is in the ask log. Apple's on-device speech turns your voice into text, and audio never leaves your Mac.

<details>
<summary><b>How the shortcut and the box work</b></summary>
<br>

Choose **Hold to talk** or **Press to toggle** in Settings → General → Shortcut behavior. Hold mode sends when you release. Toggle mode starts on the first press and sends on the second; pauses keep listening. Pressing the shortcut while Atticus answers stops it; during spoken playback it stops the voice. Esc cancels listening without sending. Toggle recordings reach a review screen after 60 seconds, rather than sending automatically. Closing the overlay or pausing Atticus stops its microphone, workers and voice.

Click any answer to copy it, including earlier answers still shown in the box. Click your request to edit and ask again, or press ↑ in an empty typing box to recall the latest request. The overlay stays within your display when resized and respects Reduce Motion. While Atticus works in a covered window, another Space, or another display, a live mini screen shows that window; the steps below show the action. The finished view stays until the next ask, typing, or a click on it. Click it to open that exact window. The preview stays on your Mac, is never sent to the AI or saved, and stops streaming when the task ends. Without Screen Recording permission, the same card shows the app icon and window title.

Apple's final transcript confirms each voice request before AI tools or learned shortcuts run. AI reasoning can start during a pause, but its tools wait for confirmation. If speech finalization takes too long, Atticus offers the partial text for review. Instant commands still skip the AI entirely. Supported built-in commands run mid-sentence, before you send. Learned shortcuts wait for confirmed words.

When Atticus acts but can't see the result, it says so ("…but I couldn't confirm the result") and doesn't learn that shortcut. Try again checks what already happened before it acts again.

</details>

## Dictate anywhere

Hold fn to talk. Double-tap to lock. In any text field, hold the fn (🌐) key, speak, then let go. Double-tap it to lock dictation on for hands-free talking; an orange ring circles the pill, and one more press inserts. fn is the shortcut until you record another in Settings → Dictation (a key combo, an F-key, or a modifier chord like fn+Control); a shortcut you already set stays. If macOS's "Press 🌐 key to" setting opens emoji, switches input source or starts Apple dictation, Settings and setup show "Set Press 🌐 key to Do Nothing" with a button to Keyboard settings. fn with another key (fn+Delete, fn+←) stays that key's shortcut. While you talk, a small pill shows a sound wave. The Dictation tab shows your words today and all time, time saved, sessions, your dictionary and history. **Verbatim** types Apple's on-device transcript with no AI. **Clean up** makes one quick AI pass that keeps your words, fixes words it clearly misheard ("talk it and it' type" becomes "talk to it and it'll type"), and drops the slips: "um" and "you know" go, "scratch that" removes the thought before it, "four, actually five" leaves five, a spoken list becomes a list, and "new line" or "question mark" become formatting. It types what you dictate and never answers or acts on it. To spell names and terms it uses your Dictionary and the text just before your cursor. It starts while you talk, so the text lands soon after you let go; if the AI's version adds or drops too much, Atticus types your words with only the obvious fillers removed. Highlight text first and Clean up tidies that text in place. Esc cancels. When the words land, the pill turns into a green check and fades. With no text field selected, it says "Nothing selected to insert — saved to History." Dictation never leaves your words on the clipboard: if a field only takes a paste, Atticus borrows the clipboard for that one paste and puts back what you had copied. If the field changes or Atticus can't confirm the words landed, it saves them to Dictation History and says "Saved to History" instead of typing twice; with History off, the words stay in the pill.

**Other languages.** Atticus runs Apple's speech in English (US). For other languages, speech that mixes languages, or more accurate English, pick **Whisper** in Settings → General → Speech model. It runs [whisper.cpp](https://github.com/ggml-org/whisper.cpp) on your Mac, so audio still never leaves it. Settings installs whisper.cpp with Homebrew (`brew install whisper.cpp`) and downloads the model you choose: **Turbo** (574 MB, the default), **Large v3** (1.1 GB, the most accurate) or **Small** (190 MB). Language is detected automatically, or you can pick one. Words show up while you talk, a little behind Apple's. Downloaded models live in `~/.config/atticus/whisper/`. Meeting Copilot still uses Apple's English model.

## Point at your screen

This is how you show Atticus something; [Draw on screen](#draw-on-screen) is how Atticus shows you. Click the pointer button, **Point at your screen**, next to the mic in the ask box. The cursor becomes a crosshair and the box says "Click, circle or scribble on anything, then ask". Mark the spot, then type or say your question and send. Another stroke near the mark replaces it; move away and your clicks reach your apps again, with the mark still showing. Atticus's own box and cards always take their clicks, so you can type while pointing. Click the pointer button again to stop or to mark somewhere else. A small picture of what you marked waits in the box; its × removes it, and Esc clears everything. Atticus gets a crop of that spot with your question, and the mark stays until you send. While a mark is waiting, instant commands and early thinking wait too.

## Draw on screen

Ask where to click or how to do something and Atticus shows you instead of only telling you: it draws boxes, circles, arrows and labels over your screen, with a pointer that moves to each spot. It goes one step at a time and moves on when you click the highlighted spot, change that value, or say "next".

Ask it to explain something and draw it ("explain the Pythagorean theorem and draw it on my screen") and the drawing builds up like a whiteboard: each step adds to the last, and a card in the opposite corner keeps every caption so far. It moves through the steps by itself. It works from what you have open: with a video, page or problem on screen, it marks up that figure and uses its numbers, unless you ask for a fresh example. Drawings go on the screen where you asked (the one with the Atticus box) unless you name another. Worked examples and practice problems are written line by line in large text on one panel, readable from your chair on a laptop or a monitor.

The drawing stays while you keep asking about it, and Atticus can add to it; it changes only when an answer draws something new. Click any mark (a box, an arrow, a label, a line of text) to select it, then ask "how does this work?": like Point at your screen, the question carries that mark and a picture of it. While a drawing is up, the Atticus box moves out of its way and comes back when it's gone. Close the card or press Esc to clear it. Steps are spoken only when Read answers aloud is on. The drawings never take focus, and clicks pass through everywhere except on a mark. Turn it off in Settings → General → Draw on screen to show you.

## Model choice

In Settings → Intelligence, choose **Cheapest**, **Balanced** (the default) or **Most capable**. Cheapest keeps every ask, meeting question and new agent on Haiku. Balanced keeps questions and quick commands on Haiku and gives real work to your work model; if a task turns multi-step, fails, or ends without a confirmed result, it continues once on the work model. Most capable uses the work model for every AI ask and agent. Instant commands skip the AI in every mode. **Work model** picks Sonnet or Opus; Opus is stronger and uses more of your plan.

With a custom server connected, Atticus uses that server's model. Under **Custom server**, choose an **Agent model** from its model list, or leave it empty to use the main model. Running agents keep their current model.

## Use a local model

Atticus can send Claude Code to a local server that implements the Anthropic Messages API. Claude Code must be installed, but you do not need a Claude account.

1. Start a server and load a model:

   | Server | Version with `/v1/messages` | Default address |
   |---|---:|---|
   | Ollama | 0.14.0+ | `http://localhost:11434` |
   | LM Studio | 0.4.1+ | `http://localhost:1234` |
   | llama.cpp `llama-server` | builds after Nov 28, 2025 | `http://localhost:8080` |
   | vLLM | 0.11.1+ | `http://localhost:8000` |

   Ollama starts with `ollama serve`; LM Studio uses `lms server start --port 1234`; llama.cpp uses `llama-server -m /path/to/model.gguf`; vLLM uses `vllm serve <model>`.
2. Open setup → **Change provider** → **Custom server**, or Settings → Intelligence → **Custom server**. If a server is on a default port, Atticus offers **Use Ollama**, **Use LM Studio**, **Use llama.cpp**, or **Use vLLM**.
3. Leave Key empty for an unauthenticated local server. Pick a model from the list Atticus reads from `GET /v1/models`, then ask normally.

Small local models are usually weaker at reliable tool use and following long screen context. Screen reading also needs a vision-capable model; text-only models can still use accessible window and page text.

## Agents

Ask for something big ("find me USB-C hubs") and Atticus hands it to a background agent. A chip shows up in the corner while you keep working. The box, the dictation pill, the chips and the done card show up on the display your mouse is on. Hover it to see the live steps and a mini screen of the work. To change course, just talk: "tell the hub agent to check HDMI too" steers the running agent instead of starting a new one. When it finishes, a card shows the result once you stop typing. During a meeting or screen share, you get a quiet notification instead. If an agent needs a permission or a connector, it asks on its chip, then carries on. Turn on agents and their connectors in Settings → Agents (or the setup step).

A long ask in the box moves to an agent by itself, with no card, and agents Atticus offers start right away. To move one sooner, press ⌃⌥↩ from any app while it runs.

Agents work behind you. Their clicks, typing, scrolling and keys go straight to the app they work in, so your pointer, your front app, your windows and your Space stay where they are. Web work happens in the agent's own browser window, in your signed-in profile; your tabs are left alone, and the window closes when the task ends. If an agent's process stops mid-task, Atticus restarts it once and it picks up where it was. When an agent asks to do something, **Always allow for this task** approves that same kind of action until the task ends; the next task asks again.

### Named agents

Say “make an agent called Researcher that finds sources and writes a short brief” to save reusable instructions, then “ask Researcher to…” to start it. Saved agents can include a folder or files and can be listed, renamed, or deleted by voice or in the Agents view.

Background agents currently require Claude Code. Pi and Devin handle foreground asks; their meeting transcripts and recaps stay local. Pi has no built-in sandbox, so Atticus disables its direct file-edit and MCP tools and Safe mode asks before every shell command; its read tools still have your account’s file access.

### Chats

Plain questions and answers can be saved in the Agents window: switch to **Chats** at the top. Chats keep only answers, never actions or agent tasks, stay on your Mac, can be renamed, and are never sent back to the AI. Turn saving off in Settings → Memory → Learning → Save chats.

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
- **An AI client:** a paid Claude plan (Pro or Max) and [Claude Code](https://claude.com/claude-code), the [Devin CLI](https://docs.devin.ai/cli) signed in to a Devin plan, [Pi](https://pi.dev) with your chosen provider/model, or a custom server through Claude Code with no Claude account. Pick one in setup (“Change provider”) or Settings → Intelligence.
- Apple's command line tools: `xcode-select --install`
- Optional, for languages other than English: [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (`brew install whisper.cpp`, or `whisper-cpp` from nixpkgs). Settings → General can install it for you.
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

The flake installs its packaged Atticus version, so macOS 26+ and Apple's command line tools are still required. Run that command again to update. `nix profile add github:SaarthurR/atticus-mac` installs an `atticus` launcher; update it with `nix profile upgrade atticus`, then run `atticus`. Nix installations show this update path in Settings instead of using Atticus's Git updater.

Working on the code instead? Clone the repo anywhere and run `./build.sh` after each change. A Devbox environment is included for Python regression tests; run `devbox shell`, then `devbox run test`.

The first launch opens a setup window. It checks your AI plan, then asks for each macOS permission.
After that, Atticus lives in the menu bar. Open it from Spotlight (⌘Space, "Atticus") for Settings: shortcut, voice, model, privacy, memory and usage. Settings and setup follow your Mac's light or dark appearance.
If you sign out of your AI client later, the setup window comes back by itself.
To see it again: `defaults delete com.atticus.app onboarded`, then restart the app.

Test: `python3 atticus.py --selftest` on macOS, plus `python3 -m unittest discover -s tests -v` for offline regressions. After building, `~/Applications/Atticus.app/Contents/MacOS/Atticus --selftest` checks native transcript matching without opening the app. Node, when installed, also checks embedded JavaScript syntax. For the UI interaction checks, run `python3 -m http.server 8765 --bind 127.0.0.1` from the repo and open `http://127.0.0.1:8765/tests/ui.html`; it uses a mock native bridge and makes no Mac actions or AI calls.

Remove: `launchctl bootout gui/$(id -u)/com.atticus.app`, then delete `~/Applications/Atticus.app`, `~/.atticus`, `~/.config/atticus` (your settings and history) and `~/Library/LaunchAgents/com.atticus.app.plist`.

## Watch for me

Say "tell me when Codex is done" or "watch this page until it says shipped". Atticus sets it up once, then checks every 5 seconds on your Mac with no AI, so waiting is free. When it fires you get a notification, and it runs a follow-up if you asked for one. A window must stay open on this desktop (covered is fine). Coding agents like Codex are watched through their own log, with no screen at all. Say "stop watching" to cancel.

## Routines

Say "every weekday at 8, summarize my calendar" or "every 30 minutes, check my inbox". Atticus saves a routine and macOS wakes it on time, so it costs nothing while it waits. Each run starts a background agent on Cheapest unless you chose another mode, and you get a notification with the result. Runs are skipped while Atticus is paused, and a restart never repeats one. See and remove routines in Settings → General → Scheduled routines, or ask Atticus to remove one. Like other agents, routines need Claude Code.

## Budget

Atticus has to stay fast and nearly free, so new features must fit under these limits:

- Instant commands: no AI, $0.
- AI asks: median under $0.002 and 6 s over the last 50 (Oct 10, 2026: $0.00095, 5.0 s). Check with `python3 atticus.py --budget`.
- System prompt: under 10,000 characters in source and at most 10,050 with the installed helper path. Every ask pays for it, and tests enforce both limits.
- Anything that waits or runs in the background: $0 while it waits. AI only to set it up and to act at the end.

## Anonymous usage

Atticus sends a random ID (made on your Mac, not tied to you) with daily use, ask outcomes, feature names, timings, dictation outcomes, and code locations for errors. It never sends task text, dictated words, file contents, paths, or screen content. Turn it off in Settings → Account & Access → Count me as a user.

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

Hands: ideas and some logic adapted from Plip (github.com/hussainn7/plip-oss, MIT). Background key authentication and menu-shortcut presses follow Cua Driver (github.com/trycua/cua, MIT).
