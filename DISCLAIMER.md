# Disclaimer

`windows10-cua-fallback` is an unofficial community workaround. It is not developed, endorsed, supported, or distributed by OpenAI or Microsoft.

The supported project shape requires the ChatGPT/Codex desktop app and its official Computer Use plugin. Standalone Codex CLI use is not claimed.

The software is provided **as is**, without warranty of any kind. Window capture and input automation can expose sensitive on-screen information, interact with the wrong UI when assumptions fail, or behave differently across Windows builds, display scaling, GPU drivers and application frameworks. You are responsible for reviewing the target, output directory, permissions and requested action before use.

In particular:

- Try the official Codex Computer Use capture path first.
- Keep tasks narrow and remain present during UI automation.
- An explicitly requested visible screen crop can include notifications or other non-activating topmost UI that overlaps the target without stealing foreground. Keep the target unobscured and inspect every captured image locally.
- Do not use this fallback on authentication dialogs, password managers, terminals, ChatGPT/Codex, Windows security/privacy settings, protected content, or other surfaces forbidden by the official Computer Use policy.
- Do not treat the included legacy runtime recovery helper as a supported Codex installation method. It relies on an internal bundle contract that can change without notice.
- Back up important data and configuration before legacy runtime replacement or other system maintenance.

To the maximum extent permitted by law, contributors are not liable for data loss, disclosure, downtime, altered settings, security incidents, failed installation, or other damages arising from use of this project.
