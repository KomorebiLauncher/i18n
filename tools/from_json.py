#!/usr/bin/env python3
"""Merge translations from the JSON catalogue (KomorebiLauncher/i18n-json) into the .ts files.

The JSON repository is where translations live; this writes them into the catalogue that
`lrelease` compiles. Matching is by key (context + sha1 of the source): a string whose source
changed in the launcher has a new key, so an old translation for the previous wording is left
alone instead of being attached to text it does not belong to.

Usage:
    python tools/from_json.py --json ../i18n-json/json --dir . [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import pathlib
import re
import sys

KEY_LEN = 12


def key_for(context: str, source: str) -> str:
    return f"{context}:{hashlib.sha1(source.encode('utf-8')).hexdigest()[:KEY_LEN]}"


def text_of(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def template_keys(catalogue: pathlib.Path) -> set[str]:
    raw = (catalogue / ".template.ts").read_text(encoding="utf-8")
    keys: set[str] = set()
    for ctx in re.findall(r"<context>(.*?)</context>", raw, re.S):
        name_m = re.search(r"<name>(.*?)</name>", ctx, re.S)
        name = text_of(name_m.group(1)).strip() if name_m else ""
        for msg in re.findall(r"<message(.*?)</message>", ctx, re.S):
            src_m = re.search(r"<source>(.*?)</source>", msg, re.S)
            if src_m:
                keys.add(key_for(name, text_of(src_m.group(1))))
    return keys


def rewrite(ts_path: pathlib.Path, translations: dict[str, str], known: set[str]) -> tuple[int, int]:
    raw = ts_path.read_text(encoding="utf-8")
    changed = skipped = 0

    def fix_context(match: re.Match) -> str:
        nonlocal changed, skipped
        block = match.group(0)
        name_m = re.search(r"<name>(.*?)</name>", block, re.S)
        name = text_of(name_m.group(1)).strip() if name_m else ""

        def fix_message(message_match: re.Match) -> str:
            nonlocal changed, skipped
            message = message_match.group(0)
            src_m = re.search(r"<source>(.*?)</source>", message, re.S)
            if not src_m:
                return message
            key = key_for(name, text_of(src_m.group(1)))
            if key not in known:
                return message
            if key not in translations:
                return message
            wanted, unfinished = translations[key]
            tr_m = re.search(r"<translation([^>]*)>(.*?)</translation>", message, re.S)
            if tr_m and 'type="vanished"' in tr_m.group(1):
                return message
            if 'numerus="yes"' in message:
                # Plural entries carry several forms whose text may contain newlines; the JSON
                # representation cannot tell them apart, so those stay as they are in the .ts.
                return message
            # Multi-line messages are common (crash reports, warnings): keep the whole text, the
            # newlines are written as-is inside <translation> just like lupdate does.
            #
            # The JSON export strips surrounding whitespace, but a few strings really start or end
            # with a space (" MiB", "Unknown loader type: "). When the two texts only differ that
            # way, keep the catalogue's spelling so a merge never eats those spaces.
            current = text_of(tr_m.group(2)) if tr_m else ""
            body = escape(current if current.strip() == wanted.strip() else wanted)
            replacement = f'<translation{" type=\'unfinished\'" if unfinished else ""}>{body}</translation>'
            if tr_m:
                if text_of(tr_m.group(2)).strip() == wanted.strip() and (("unfinished" in tr_m.group(1)) == unfinished):
                    return message
                new_message = message[: tr_m.start()] + replacement + message[tr_m.end() :]
                if new_message == message:
                    # the text differs only in ways escaping puts back: not a real change
                    return message
                changed += 1
                return new_message
            skipped += 1
            return message

        return re.sub(r"<message\b.*?</message>", fix_message, block, flags=re.S)

    updated = re.sub(r"<context>.*?</context>", fix_context, raw, flags=re.S)
    if updated != raw:
        ts_path.write_text(updated, encoding="utf-8", newline="")
    return changed, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="directory holding the per-language JSON files")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    catalogue = pathlib.Path(args.dir)
    json_dir = pathlib.Path(args.json)
    known = template_keys(catalogue)

    totals = {"languages": 0, "changed": 0, "skipped": 0}
    for path in sorted(json_dir.glob("*.json")):
        lang = path.stem
        ts_path = catalogue / f"{lang}.ts"
        if not ts_path.exists():
            print(f"skip {lang}: no .ts in the catalogue")
            continue
        entries = json.loads(path.read_text(encoding="utf-8"))
        translations = {
            e["key"]: (e["translation"], "[unfinished]" in e.get("context", ""))
            for e in entries
            if e.get("translation") and e["key"] in known
        }
        if args.dry_run:
            print(f"{lang}: {len(translations)} translations available (dry run)")
            totals["languages"] += 1
            continue
        changed, skipped = rewrite(ts_path, translations, known)
        totals["languages"] += 1
        totals["changed"] += changed
        totals["skipped"] += skipped
        if changed or skipped:
            print(f"{lang}: {changed} written, {skipped} skipped")

    print(json.dumps(totals, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
