#!/usr/bin/env python3
"""Pull translations from ParaTranz and write them back into the .ts catalogue.

ParaTranz holds one file per language (zh.json, de.json, ...), imported from the export of
tools/export.py, so every string carries the key `Context:sha1(source)[:12]`. That key is what
makes the round trip safe: a string whose source text changed in the launcher gets a new key and
is simply left alone here, instead of being matched to the wrong translation.

Usage:
    python tools/paratranz.py --token <token> --dir . [--dry-run] [--languages zh,de]

The token needs read access to the project; it is passed in by the workflow from a secret.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

API = "https://paratranz.cn/api"
PAGE_SIZE = 1000
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


def fetch(url: str, token: str):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "komorebi-i18n"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def project_files(token: str, project: int):
    return fetch(f"{API}/projects/{project}/files", token)


def strings_for_file(token: str, project: int, file_id: int):
    """Yield every string in a file, page by page."""
    page = 1
    while True:
        data = fetch(f"{API}/projects/{project}/strings?page={page}&pageSize={PAGE_SIZE}&file={file_id}", token)
        yield from data.get("results", [])
        if page >= data.get("pageCount", 1):
            break
        page += 1


def template_keys(catalogue: pathlib.Path) -> dict[str, tuple[str, str]]:
    """key -> (context, source) for every source string the launcher currently has."""
    raw = (catalogue / ".template.ts").read_text(encoding="utf-8")
    keys: dict[str, tuple[str, str]] = {}
    for ctx in re.findall(r"<context>(.*?)</context>", raw, re.S):
        name_m = re.search(r"<name>(.*?)</name>", ctx, re.S)
        name = text_of(name_m.group(1)).strip() if name_m else ""
        for msg in re.findall(r"<message(.*?)</message>", ctx, re.S):
            src_m = re.search(r"<source>(.*?)</source>", msg, re.S)
            if src_m:
                keys[key_for(name, text_of(src_m.group(1)))] = (name, text_of(src_m.group(1)))
    return keys


def rewrite(ts_path: pathlib.Path, translations: dict[str, str], known: dict[str, tuple[str, str]]) -> tuple[int, int]:
    """Write translations into one .ts file. Returns (changed, skipped)."""
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
            source = text_of(src_m.group(1))
            if key_for(name, source) not in known:
                return message                      # string no longer in the launcher
            wanted = translations.get(key_for(name, source))
            if not wanted:
                return message                      # nothing translated on ParaTranz (yet)
            tr_m = re.search(r"<translation([^>]*)>(.*?)</translation>", message, re.S)
            if tr_m and 'type="vanished"' in tr_m.group(1):
                return message                      # removed string, leave the note alone
            plural = 'numerus="yes"' in message
            if plural:
                forms = [line for line in wanted.split("\n") if line.strip()]
                body = "\n" + "".join(f"            <numerusform>{escape(f)}</numerusform>\n" for f in forms) + "        "
            else:
                body = escape(wanted.split("\n")[0])
            replacement = f"<translation>{body}</translation>"
            if tr_m:
                if text_of(tr_m.group(2)).strip() == wanted.strip() and "unfinished" not in tr_m.group(1):
                    return message                  # already current
                new_message = message[: tr_m.start()] + replacement + message[tr_m.end() :]
            else:
                skipped += 1
                return message
            changed += 1
            return new_message

        return re.sub(r"<message\b.*?</message>", fix_message, block, flags=re.S)

    updated = re.sub(r"<context>.*?</context>", fix_context, raw, flags=re.S)
    if updated != raw:
        ts_path.write_text(updated, encoding="utf-8", newline="")
    return changed, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--project", type=int, default=21325)
    ap.add_argument("--dir", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--languages", default="", help="comma separated, default all")
    args = ap.parse_args()

    catalogue = pathlib.Path(args.dir)
    known = template_keys(catalogue)
    only = {s.strip() for s in args.languages.split(",") if s.strip()}

    files = project_files(args.token, args.project)
    totals = {"languages": 0, "changed": 0, "skipped": 0, "strings": 0}

    for entry in sorted(files, key=lambda f: f["name"]):
        name = entry.get("name", "")
        if not name.endswith(".json"):
            continue
        lang = name[: -len(".json")]
        ts_path = catalogue / f"{lang}.ts"
        if not ts_path.exists():
            print(f"skip {lang}: no .ts in the catalogue")
            continue
        if only and lang not in only:
            continue

        translations: dict[str, str] = {}
        for item in strings_for_file(args.token, args.project, entry["id"]):
            translation = (item.get("translation") or "").strip()
            if translation and item.get("stage", 1) >= 1:
                translations[item["key"]] = translation
        totals["strings"] += len(translations)

        if args.dry_run:
            print(f"{lang}: {len(translations)} translated strings on ParaTranz (dry run, not written)")
            totals["languages"] += 1
            continue

        changed, skipped = rewrite(ts_path, translations, known)
        totals["changed"] += changed
        totals["skipped"] += skipped
        totals["languages"] += 1
        if changed or skipped:
            print(f"{lang}: {changed} written, {skipped} skipped")

    print(json.dumps(totals, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
