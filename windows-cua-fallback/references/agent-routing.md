# Optional AGENTS.md routing snippet

Use this only when a user explicitly asks to add persistent routing guidance to an existing `AGENTS.md`. Review and adapt the block before writing it. Do not create, replace, or edit `AGENTS.md` merely because the fallback skill was installed.

```md
## Computer and browser use

- Prefer a dedicated plugin or MCP server when it provides the required structured operation.
- For native Windows applications, read the installed `computer-use` skill and use the official Computer Use path first. Refresh the app/window inventory before selecting a target, and do not declare native Computer Use unavailable solely because a browser-oriented surface returned no apps.
- Use `@Chrome` when a task needs the user's existing authenticated browser profile, open tabs, or browser extensions. Use `@Browser` for a separate browser profile, local web apps, or an isolated browsing session.
- Follow observe → one action → refresh. Never reuse stale element indexes, screenshot IDs, coordinates, or window objects.
- Use `$windows-cua-fallback` only after the official native screenshot path has reproducibly failed while the exact target window remains enumerable and controllable. Keep all official Computer Use approvals, confirmation rules, and forbidden-surface restrictions in force.
- Never use the fallback for browsers, terminals, ChatGPT/Codex, authentication dialogs, password managers, or Windows security and privacy settings.
```
