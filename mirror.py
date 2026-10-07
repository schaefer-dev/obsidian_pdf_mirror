#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mirror an Obsidian vault into a folder tree of PDFs (pandoc -> Typst).

Only notes whose content (or embedded images/notes) changed since the last run
are re-rendered. PDFs whose note was deleted or renamed are removed. State is
kept in .state/state.json next to this script.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
RENDER_DIR = PROJECT_DIR / "render"
STATE_DIR = PROJECT_DIR / ".state"
TEMPLATE = RENDER_DIR / "template.typ"
LUA_FILTER = RENDER_DIR / "obsidian.lua"
STATE_VERSION = 1

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
MAX_EMBED_DEPTH = 2
LOG_MAX_BYTES = 2_000_000
# Refuse to delete more than this share of the mirror in one run without --force.
DELETE_GUARD_RATIO = 0.3
DELETE_GUARD_MIN = 20

PANDOC_FROM = (
    "commonmark_x-alerts-yaml_metadata_block-subscript-superscript"
    "+hard_line_breaks+autolink_bare_uris"
)


def nfc(s: str) -> str:
    """Paths are compared in NFC: Dropbox rewrites names to NFD, APFS accepts both."""
    return unicodedata.normalize("NFC", s)


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def notify(title: str, msg: str) -> None:
    """Best-effort macOS notification for problems that need a human."""
    script = f"display notification {json.dumps(msg)} with title {json.dumps(title)}"
    subprocess.run(["osascript", "-e", script], capture_output=True)


# --------------------------------------------------------------------------- config


@dataclass
class Config:
    vault: Path
    output: Path
    exclude: list[str]
    jobs: int
    paper: str
    font: str
    codefont: str
    lang: str

    @classmethod
    def load(cls, path: Path) -> Config:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        return cls(
            vault=Path(raw["vault"]).expanduser(),
            output=Path(raw["output"]).expanduser(),
            exclude=list(raw.get("exclude", [])),
            jobs=int(raw.get("jobs", 4)),
            paper=raw.get("paper", "a4"),
            font=raw.get("font", "Helvetica Neue"),
            codefont=raw.get("codefont", "Menlo"),
            lang=raw.get("lang", "de"),
        )

    def render_settings(self) -> dict:
        return {"paper": self.paper, "font": self.font, "codefont": self.codefont, "lang": self.lang}


# --------------------------------------------------------------------------- vault scan


@dataclass
class Vault:
    root: Path
    notes: dict[str, tuple[int, int]]  # rel path -> (mtime_ns, size), excluded notes omitted
    files: dict[str, int]  # every non-hidden file (incl. excluded notes) -> mtime_ns
    by_name: dict[str, list[str]] = field(default_factory=dict)  # lowercase basename -> rel paths

    def resolve(self, link: str, from_note: str, default_ext: str = ".md") -> str | None:
        """Resolve an Obsidian link target the way Obsidian does (roughly)."""
        link = nfc(link.strip().lstrip("/"))
        if not link:
            return None
        if default_ext and not link.lower().endswith(default_ext):
            # "Note" or "Note.v2" -> try with .md first, then as-is (e.g. "doc.pdf")
            candidates = [link + default_ext, link]
        else:
            candidates = [link]
        for cand in candidates:
            if cand in self.files:
                return cand
            hits = self.by_name.get(os.path.basename(cand).lower(), [])
            if "/" in cand:
                suffix = "/" + cand.lower()
                hits = [h for h in hits if ("/" + h.lower()).endswith(suffix)]
            if not hits:
                continue
            note_dir = os.path.dirname(from_note)
            same_dir = [h for h in hits if os.path.dirname(h) == note_dir]
            return (same_dir or sorted(hits, key=lambda h: (h.count("/"), len(h), h)))[0]
        return None


def is_excluded(rel: str, patterns: list[str]) -> bool:
    name = os.path.basename(rel)
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns)


def scan_vault(root: Path, exclude: list[str]) -> Vault:
    notes: dict[str, tuple[int, int]] = {}
    files: dict[str, int] = {}
    by_name: dict[str, list[str]] = {}

    def walk(dir_path: str, rel_dir: str, excluded: bool) -> None:
        with os.scandir(dir_path) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue  # .obsidian, .git, .trash, .DS_Store, ...
                rel = nfc(f"{rel_dir}/{entry.name}" if rel_dir else entry.name)
                if entry.is_dir(follow_symlinks=False):
                    walk(entry.path, rel, excluded or is_excluded(rel, exclude))
                elif entry.is_file():
                    st = entry.stat()
                    files[rel] = st.st_mtime_ns
                    by_name.setdefault(os.path.basename(rel).lower(), []).append(rel)
                    if (
                        entry.name.lower().endswith(".md")
                        and not excluded
                        and not is_excluded(rel, exclude)
                    ):
                        notes[rel] = (st.st_mtime_ns, st.st_size)

    walk(str(root), "", False)
    return Vault(root=root, notes=notes, files=files, by_name=by_name)


def scan_mirror(root: Path) -> set[str]:
    found: set[str] = set()
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        for name in filenames:
            if name.lower().endswith(".pdf"):
                found.add(nfc(name if rel_dir == "." else f"{rel_dir}/{name}"))
    return found


def pdf_rel(note_rel: str) -> str:
    return note_rel[:-3] + ".pdf"


# --------------------------------------------------------------------------- preprocessing

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")
COMMENT_RE = re.compile(r"%%.*?%%", re.S)
EMBED_RE = re.compile(r"!\[\[([^\]\n]+)\]\]")
WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
HIGHLIGHT_RE = re.compile(r"(?<![=\\])==(?=\S)([^=\n]+?)(?<=\S)==(?!=)")
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
BLOCK_ID_RE = re.compile(r"[ \t]\^[A-Za-z0-9-]+[ \t]*$", re.M)
MD_ESCAPE_RE = re.compile(r"([\\`*_{}\[\]<>#+!|$~=])")


def md_escape(s: str) -> str:
    return MD_ESCAPE_RE.sub(r"\\\1", s)


def split_fences(text: str) -> list[tuple[bool, str]]:
    """Split markdown into (is_code, chunk) pieces along fenced code blocks."""
    out: list[tuple[bool, str]] = []
    buf: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                if buf:
                    out.append((False, "".join(buf)))
                buf, fence = [line], m.group(1)
            else:
                buf.append(line)
        else:
            buf.append(line)
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
                and line.strip() == m.group(1)
            ):
                out.append((True, "".join(buf)))
                buf, fence = [], None
    if buf:
        out.append((fence is not None, "".join(buf)))
    return out


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def extract_section(text: str, heading: str) -> str | None:
    """Return the section under `heading` (up to the next heading of same or higher level)."""
    want = heading.strip().lower()
    lines = text.splitlines(keepends=True)
    start = level = None
    in_code = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_code = not in_code
        if in_code:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        if start is None:
            if m.group(2).strip().lower() == want:
                start, level = i, len(m.group(1))
        elif len(m.group(1)) <= level:
            return "".join(lines[start:i])
    return "".join(lines[start:]) if start is not None else None


def extract_block(text: str, block_id: str) -> str | None:
    """Return the paragraph (or single list item) carrying `^block_id`."""
    marker = re.compile(r"[ \t]\^" + re.escape(block_id) + r"[ \t]*$")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not marker.search(line):
            continue
        start = i
        if not LIST_ITEM_RE.match(line):
            while (
                start > 0
                and lines[start - 1].strip()
                and not HEADING_RE.match(lines[start - 1])
                and not LIST_ITEM_RE.match(lines[start - 1])
            ):
                start -= 1
        return "\n".join(lines[start:i] + [marker.sub("", line)])
    return None


def link_label(target: str) -> str:
    """'Note#Heading' -> 'Note › Heading', 'Note#^id' -> 'Note', '#Heading' -> 'Heading'."""
    page, _, sub = target.partition("#")
    page = os.path.basename(page)
    if page.lower().endswith(".md"):
        page = page[:-3]
    if not sub or sub.startswith("^"):
        return page
    sub = sub.replace("#", " › ")
    return f"{page} › {sub}" if page else sub


class Preprocessor:
    def __init__(self, vault: Vault):
        self.vault = vault

    def run(self, note_rel: str, text: str) -> tuple[str, dict[str, int | None]]:
        deps: dict[str, int | None] = {}
        out = self._process(note_rel, strip_frontmatter(text), deps, depth=0, stack=(note_rel,))
        return out, deps

    def _process(self, note_rel, text, deps, depth, stack) -> str:
        parts = []
        for is_code, chunk in split_fences(text):
            if is_code:
                parts.append(chunk)
            else:
                chunk = COMMENT_RE.sub("", chunk)
                parts.append(self._inline(note_rel, chunk, deps, depth, stack))
        return "".join(parts)

    def _inline(self, note_rel, chunk, deps, depth, stack) -> str:
        pieces = []
        pos = 0
        for m in INLINE_CODE_RE.finditer(chunk):
            pieces.append(self._transform(note_rel, chunk[pos : m.start()], deps, depth, stack))
            pieces.append(m.group(0))
            pos = m.end()
        pieces.append(self._transform(note_rel, chunk[pos:], deps, depth, stack))
        return "".join(pieces)

    def _transform(self, note_rel, s, deps, depth, stack) -> str:
        s = EMBED_RE.sub(lambda m: self._embed(note_rel, m.group(1), deps, depth, stack), s)
        s = WIKILINK_RE.sub(lambda m: self._wikilink(m.group(1)), s)
        s = HIGHLIGHT_RE.sub(r"[\1]{.mark}", s)
        s = BLOCK_ID_RE.sub("", s)
        return s

    @staticmethod
    def _split(inner: str) -> tuple[str, str]:
        parts = re.split(r"\\?\|", inner, maxsplit=1)
        return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")

    def _wikilink(self, inner: str) -> str:
        target, alias = self._split(inner)
        label = alias or link_label(target)
        return f"[{md_escape(label)}]{{.wikilink}}"

    def _embed(self, note_rel, inner, deps, depth, stack) -> str:
        target, opts = self._split(inner)
        page, _, sub = target.partition("#")
        ext = os.path.splitext(page)[1].lower()
        name = os.path.basename(page) or page

        if ext in IMAGE_EXTS:
            rel = self.vault.resolve(page, note_rel, default_ext="")
            if rel is None:
                deps["?file:" + page] = None
                return f"*\\[missing image: {md_escape(name)}\\]*"
            deps[rel] = self.vault.files[rel]
            attr = ""
            size = re.match(r"^(\d+)(?:x(\d+))?$", opts)
            if size:
                attr = f"{{width={size.group(1)}px}}"
            return f"![](</{rel}>){attr}"

        if ext and ext != ".md":
            return f"*\\[attachment: {md_escape(name)}\\]*"

        rel = self.vault.resolve(page, note_rel) if page else note_rel
        if rel is None or not rel.lower().endswith(".md"):
            deps["?note:" + page] = None
            return f"*\\[missing note: {md_escape(link_label(target))}\\]*"
        title = opts or link_label(target) or name
        if depth >= MAX_EMBED_DEPTH or (rel in stack and not sub):
            return f"*\\[embedded note: {md_escape(title)}\\]*"
        if rel != note_rel:
            deps[rel] = self.vault.files[rel]
        try:
            body = strip_frontmatter((self.vault.root / rel).read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            return f"*\\[missing note: {md_escape(title)}\\]*"
        if sub.startswith("^"):
            body = extract_block(body, sub[1:])
        elif sub:
            body = extract_section(body, sub.split("#")[-1])
        if body is None:
            return f"*\\[missing section: {md_escape(title)}\\]*"
        inner_md = self._process(rel, body, deps, depth + 1, stack + (rel,))
        safe_title = title.replace('"', "'").replace("\\", "/")
        fence = ":" * (6 - depth)
        return f'\n\n{fence} {{.obsidian-embed title="{safe_title}"}}\n{inner_md.strip()}\n{fence}\n\n'


# --------------------------------------------------------------------------- rendering


class RenderError(Exception):
    pass


def render_note(cfg: Config, vault: Vault, rel: str, text: str, deps_out: dict, tmp_dir: Path) -> Path:
    md, deps = Preprocessor(vault).run(rel, text)
    deps_out.update(deps)
    note_dir = os.path.dirname(rel)
    title = os.path.splitext(os.path.basename(rel))[0]
    first_line = next((line for line in md.splitlines() if line.strip()), "")
    # Notes often start with "# <filename>"; don't print the title twice.
    show_title = first_line.strip().lstrip("#").strip().lower() != title.lower() or not first_line.startswith("# ")
    settings = cfg.render_settings()
    pandoc_cmd = [
        "pandoc",
        "-f", PANDOC_FROM,
        "-t", "typst",
        "--standalone",
        "--template", str(TEMPLATE),
        "--lua-filter", str(LUA_FILTER),
        "-M", f"title={title}",
        "-M", f"notepath={rel[:-3]}",
        "-M", f"vaultroot={vault.root}",
        "-M", f"notedir={note_dir}",
        *(["-V", "showtitle=true"] if show_title else []),
        "-V", f"paper={settings['paper']}",
        "-V", f"mainfont={settings['font']}",
        "-V", f"codefont={settings['codefont']}",
        "-V", f"lang={settings['lang']}",
    ]
    p = subprocess.run(pandoc_cmd, input=md.encode(), capture_output=True, timeout=120)
    if p.returncode != 0:
        raise RenderError(f"pandoc: {p.stderr.decode(errors='replace').strip()}")

    fd, name = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
    os.close(fd)
    out = Path(name)
    typst_cmd = [
        "typst", "compile",
        "--root", str(vault.root),
        "--format", "pdf",
        # Deterministic output: identical input -> identical bytes -> no Dropbox upload.
        "--creation-timestamp", str(vault.notes[rel][0] // 1_000_000_000),
        "-", str(out),
    ]
    t = subprocess.run(typst_cmd, input=p.stdout, capture_output=True, timeout=120)
    if t.returncode != 0:
        out.unlink(missing_ok=True)
        raise RenderError(f"typst: {t.stderr.decode(errors='replace').strip()}")
    return out


def install_pdf(tmp: Path, dest: Path) -> bool:
    """Move tmp into place unless dest already has identical bytes. Returns True if written."""
    try:
        if dest.exists() and dest.stat().st_size == tmp.stat().st_size and dest.read_bytes() == tmp.read_bytes():
            tmp.unlink()
            return False
    except OSError:
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(tmp, dest)
    except OSError:  # different volume
        shutil.move(str(tmp), str(dest))
    return True


# --------------------------------------------------------------------------- state


def file_identity(path: Path) -> str:
    st = path.stat()
    return f"{path}:{st.st_size}:{st.st_mtime_ns}"


def renderer_hash(cfg: Config) -> str:
    h = hashlib.sha256()
    for f in (Path(__file__).resolve(), TEMPLATE, LUA_FILTER):
        h.update(f.read_bytes())
    h.update(json.dumps(cfg.render_settings(), sort_keys=True).encode())
    for tool in ("pandoc", "typst"):
        exe = shutil.which(tool)
        if exe is None:
            raise SystemExit(f"{tool} not found on PATH")
        h.update(file_identity(Path(exe).resolve()).encode())
    return h.hexdigest()[:16]


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
        if state.get("version") == STATE_VERSION:
            return state
    except (OSError, ValueError):
        pass
    return {"version": STATE_VERSION, "renderer": None, "notes": {}}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)


def deps_unchanged(vault: Vault, note_rel: str, deps: dict[str, int | None]) -> bool:
    for key, mtime in deps.items():
        if key.startswith("?file:"):
            if vault.resolve(key[6:], note_rel, default_ext="") is not None:
                return False
        elif key.startswith("?note:"):
            if vault.resolve(key[6:], note_rel) is not None:
                return False
        elif vault.files.get(key) != mtime:
            return False
    return True


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- main


def prune_empty_dirs(root: Path) -> None:
    for dirpath, _, _ in os.walk(root, topdown=False):
        if Path(dirpath) == root:
            continue
        entries = os.listdir(dirpath)
        if all(e == ".DS_Store" for e in entries):
            for e in entries:
                os.unlink(os.path.join(dirpath, e))
            os.rmdir(dirpath)


def rotate_log() -> None:
    logf = STATE_DIR / "mirror.log"
    try:
        if logf.stat().st_size > LOG_MAX_BYTES:
            os.replace(logf, logf.with_suffix(".log.1"))
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=PROJECT_DIR / "config.toml")
    ap.add_argument("--state", type=Path, default=STATE_DIR / "state.json", help=argparse.SUPPRESS)
    ap.add_argument("--full", action="store_true", help="re-render every note")
    ap.add_argument("--dry-run", action="store_true", help="only report what would happen")
    ap.add_argument("--only", action="append", default=[], metavar="REL_PATH",
                    help="render only these notes (vault-relative; no deletions); repeatable")
    ap.add_argument("--force", action="store_true", help="allow large deletions")
    ap.add_argument("-j", "--jobs", type=int)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cfg = Config.load(args.config)
    jobs = args.jobs or cfg.jobs
    vault_root, out_root = cfg.vault.resolve(), cfg.output.resolve()
    if vault_root == out_root or vault_root in out_root.parents or out_root in vault_root.parents:
        log(f"error: vault and output must not contain each other ({vault_root}, {out_root})")
        return 2

    STATE_DIR.mkdir(exist_ok=True)
    rotate_log()
    lock = open(STATE_DIR / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if args.verbose or sys.stdout.isatty():
            log("another run is in progress, exiting")
        return 0

    started = time.monotonic()
    if not vault_root.is_dir():
        log(f"error: vault not found: {vault_root}")
        return 2
    vault = scan_vault(vault_root, cfg.exclude)
    if not vault.notes:
        log("error: vault contains no notes; refusing to touch the mirror")
        return 2

    state = load_state(args.state)
    rhash = renderer_hash(cfg)
    renderer_changed = state.get("renderer") != rhash
    old_notes: dict[str, dict] = state["notes"]
    existing = scan_mirror(out_root)

    # ---- deletions (before rendering: a case-only rename must not delete the new PDF)
    expected = {pdf_rel(r) for r in vault.notes}
    orphans = sorted(existing - expected) if not args.only else []
    if (
        len(existing) >= DELETE_GUARD_MIN
        and len(orphans) > DELETE_GUARD_RATIO * len(existing)
        and not args.force
    ):
        msg = f"would delete {len(orphans)} of {len(existing)} PDFs; run mirror.py --force if intended"
        log(f"error: {msg}")
        notify("Obsidian PDF mirror paused", msg)
        return 3

    # ---- decide what to render
    to_render: list[str] = []
    new_notes: dict[str, dict] = {}
    candidates = args.only or sorted(vault.notes)
    for rel in candidates:
        if rel not in vault.notes:
            log(f"warning: not a mirrored note: {rel}")
            continue
        mtime, size = vault.notes[rel]
        rec = old_notes.get(rel)
        if args.full or args.only or renderer_changed or rec is None:
            to_render.append(rel)
            continue
        if not deps_unchanged(vault, rel, rec.get("deps", {})):
            to_render.append(rel)
            continue
        if (rec["mtime"], rec["size"]) != (mtime, size):
            if sha256_file(vault_root / rel) != rec.get("sha"):
                to_render.append(rel)
                continue
            rec = {**rec, "mtime": mtime, "size": size}  # touched, content unchanged
        if rec.get("ok") and pdf_rel(rel) not in existing:
            to_render.append(rel)  # PDF was removed from the mirror by hand
        else:
            new_notes[rel] = rec
    if args.only:  # keep everything else as it was
        new_notes = {**{k: v for k, v in old_notes.items() if k in vault.notes}, **new_notes}

    if args.dry_run:
        for o in orphans:
            log(f"would delete  {o}")
        for r in to_render:
            log(f"would render  {r}")
        log(f"dry run: {len(to_render)} to render, {len(orphans)} to delete, "
            f"{len(vault.notes) - len(to_render)} up to date")
        return 0

    deleted = 0
    for o in orphans:
        try:
            (out_root / o).unlink()
            deleted += 1
            if args.verbose:
                log(f"deleted   {o}")
        except FileNotFoundError:
            pass
    if orphans:
        prune_empty_dirs(out_root)

    # ---- render
    tmp_dir = STATE_DIR / "tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)  # leftovers from an interrupted run
    tmp_dir.mkdir()
    out_root.mkdir(parents=True, exist_ok=True)
    written = unchanged = failed = 0

    def job(rel: str) -> tuple[str, dict, bool | None, str | None]:
        mtime, size = vault.notes[rel]
        raw = (vault_root / rel).read_bytes()
        rec = {"mtime": mtime, "size": size, "sha": hashlib.sha256(raw).hexdigest(), "deps": {}, "ok": False}
        try:
            tmp = render_note(cfg, vault, rel, raw.decode("utf-8-sig", errors="replace"), rec["deps"], tmp_dir)
            changed = install_pdf(tmp, out_root / pdf_rel(rel))
            rec["ok"] = True
            return rel, rec, changed, None
        except (RenderError, subprocess.TimeoutExpired, OSError) as e:
            return rel, rec, None, str(e)

    if to_render:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for fut in as_completed([pool.submit(job, r) for r in to_render]):
                rel, rec, changed, err = fut.result()
                new_notes[rel] = rec
                if err:
                    failed += 1
                    log(f"FAILED    {rel}\n{err}")
                elif changed:
                    written += 1
                    if args.verbose:
                        log(f"rendered  {rel}")
                else:
                    unchanged += 1

    state = {"version": STATE_VERSION, "renderer": rhash, "notes": new_notes}
    save_state(args.state, state)

    if to_render or deleted or args.verbose or sys.stdout.isatty():
        log(
            f"{len(vault.notes)} notes: {written} written, {unchanged} re-rendered identical, "
            f"{deleted} deleted, {failed} failed, "
            f"{len(vault.notes) - len(to_render)} skipped ({time.monotonic() - started:.1f}s)"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
