# Obsidian → PDF mirror

Keeps a PDF copy of every note in an Obsidian vault in a separate folder tree (e.g. in Dropbox),
using pandoc → Typst. Runs every 15 minutes via launchd and only re-renders notes that changed.

- **Incremental:** notes whose mtime/size, content hash and embedded files (images, transcluded notes)
  are unchanged are skipped. An idle run takes ~0.1 s.
- **Deletions and renames:** PDFs without a matching note are removed, and empty folders are pruned.
- **Deterministic output:** re-rendering an unchanged note produces identical bytes, so the file is
  not rewritten and Dropbox doesn't re-upload it.
- **Safety:** does nothing if the vault is missing or empty. Refuses to delete more than 30% of the
  mirror in one run (shows a notification; run with `--force` to proceed).

Obsidian syntax handled: wikilinks (as text), image embeds `![[img.png|300]]`, note/section/block
embeds `![[Note#Heading]]`, callouts, `==highlights==`, `%%comments%%`, tasks, tables, math, footnotes.
Dataview queries and Mermaid diagrams are shown as code. PDF and other attachment embeds become placeholders.

## Setup (any Mac)

1. Edit `config.toml` (vault path, output path, excludes).
2. `./install.sh` installs pandoc and typst (Homebrew), uv if missing, and the launchd agent.
   The first run starts immediately (~30 s for ~900 notes).

`./uninstall.sh` removes the agent.

## Manual use

```sh
uv run mirror.py --dry-run        # show what would change
uv run mirror.py -v               # sync now, list each file
uv run mirror.py --full           # re-render everything
uv run mirror.py --only "04 - Tech/Note.md"
launchctl kickstart gui/$(id -u)/local.obsidian-pdf-mirror   # trigger the agent now
```

## Files

| Path | Purpose |
|---|---|
| `mirror.py` | Scan, change detection, Obsidian-syntax preprocessing, rendering, deletions |
| `render/obsidian.lua` | pandoc filter: callouts, embeds, tasks, images, links |
| `render/template.typ` | pandoc Typst template: page layout, fonts, callout styles |
| `launchd/mirror.plist.template` | launchd agent, filled in by `install.sh` |
| `.state/` | state.json, mirror.log (gitignored, machine-local) |

Changing `mirror.py`, the filter, the template or the render settings in `config.toml` re-renders
all notes automatically on the next run.
