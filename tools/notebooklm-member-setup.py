#!/usr/bin/env python3
"""notebooklm-member-setup.py — make a teammate's OWN NotebookLM notebooks for a shared vault.

Run it yourself, on your own computer, signed in to NotebookLM with your own Google
account (notebooklm login). It:
  1. creates, in YOUR Google account: a reminder notebook (the vault's rules and
     lessons), a general notebook (pages that belong to no project), one notebook per
     project you SHARE with the vault owner (--shared, using the owner's project
     labels), and one per project of your OWN (--own);
  2. writes members/<you>/notebooklm.py (only you can change it): your notebook ids,
     your own projects' pages, and the notebooks already in your account as IGNORED;
  3. fills each new notebook from the vault and checks every upload landed
     (tools/notebooklm-wiki-refresh.py; records in members/<you>/notebooklm-state/).
The owner's projects you don't list are never uploaded for you. Run it again with more
--shared / --own to add notebooks later; the ones you have are kept. If a run stops part way
(your computer sleeps, the network drops), run the same command again: it fills only what
is still missing.

  python3.11 tools/notebooklm-member-setup.py --list
  python3.11 tools/notebooklm-member-setup.py --shared openfirehouse,firehazmat,the-match
  python3.11 tools/notebooklm-member-setup.py --own "my-app=My App=wiki/apps/my-app.md,wiki/synthesis/my-app-"

  --list      the owner's project labels you can pass to --shared, then exit
  --dry-run   say what it would create and write; change nothing
  --no-fill   create the notebooks and write your file, but upload nothing yet
Then commit members/<you>/ (your agent asks you first).
"""
import argparse
import datetime
import json
import pprint
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
VAULT = TOOLS.parent
REFRESH = TOOLS / "notebooklm-wiki-refresh.py"
sys.path.insert(0, str(TOOLS))
import limitless_member as lm  # noqa: E402


def fail(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def nb_json(args):
    r = subprocess.run(["notebooklm", *args, "--json"], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"notebooklm {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return json.loads(r.stdout)


def parse_own(spec):
    parts = spec.split("=")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        fail(f'--own "{spec}": expected "label=Display Name=prefix1,prefix2"')
    label, display, prefixes = (p.strip() for p in parts)
    return label, display, [p.strip() for p in prefixes.split(",") if p.strip()]


def write_member_file(path, login, notebooks, own_routes, ignored):
    today = datetime.date.today().isoformat()
    body = (
        f"# members/{login}/notebooklm.py — {login}'s OWN NotebookLM notebooks for this shared vault.\n"
        f"# Only {login} can change this file (the vault's authorship rule). Made by\n"
        f"# tools/notebooklm-member-setup.py ({today}); run it again to add notebooks.\n"
        "# How the tools use it: tools/limitless_member.py.\n\n"
        "# label -> notebook id in your Google account. 'reminder' = the rules and lessons;\n"
        "# the default label = pages that belong to no project; the rest = your projects.\n"
        f"NOTEBOOKS = {pprint.pformat(notebooks, sort_dicts=False, width=100)}\n\n"
        "# Your own projects: (vault path prefix, label, display name). Matched before the vault's.\n"
        f"OWN_ROUTES = {pprint.pformat(own_routes, width=100)}\n\n"
        "# Notebooks in your account that are not part of this vault (Roll Call won't flag them).\n"
        f"IGNORED = {pprint.pformat(ignored, sort_dicts=False, width=100)}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Make your own NotebookLM notebooks for this shared vault.")
    ap.add_argument("--shared", default="", help="comma-separated project labels you share with the vault owner")
    ap.add_argument("--own", action="append", default=[], help='"label=Display Name=prefix1,prefix2" (repeatable)')
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-fill", action="store_true")
    args = ap.parse_args()

    manifest = lm.load_manifest(VAULT)
    if manifest is None:
        fail("this vault has no .limitless-project.py")
    owner = getattr(manifest, "VAULT_OWNER", "") or ""
    nbm = getattr(manifest, "NOTEBOOKLM", {}) or {}
    displays = {}
    for _prefix, _nbid, label, display in nbm.get("routes", []):
        displays.setdefault(label, display)
    default_label = (nbm.get("default") or ("", "wiki", "wiki"))[1]
    project = getattr(manifest, "PROJECT_ID", "vault") or "vault"

    if args.list:
        print("The vault owner's project labels (pass the ones you share to --shared):")
        for label in displays:
            print(f"  {label}")
        return 0

    login, teammate = lm.runner(VAULT, owner)
    if not teammate:
        fail("this is for a teammate in a shared vault. You are the vault owner here, or the vault "
             "isn't shared (no .authors.json / VAULT_OWNER): your notebooks are the ones in the manifest.")
    if login.startswith("unknown"):
        fail(f"your commit email isn't in .authors.json ({login}). Commit with an email listed under "
             "your GitHub login, then run this again.")

    shared = [x.strip() for x in args.shared.split(",") if x.strip()]
    unknown = [x for x in shared if x not in displays]
    if unknown:
        fail(f"--shared: {', '.join(unknown)} is not one of the owner's projects "
             f"({', '.join(displays)}). See --list.")
    own = [parse_own(s) for s in args.own]
    for label, _display, _prefixes in own:
        if label in displays or label in ("reminder", default_label):
            fail(f"--own: '{label}' is already a label here; pick a name for your own project")

    mf = lm.member_file(VAULT, login)
    notebooks, own_routes, ignored, first_time = {}, [], {}, True
    if mf.exists():
        first_time = False
        cur = lm._load_py(mf, "_setup_member_file")
        notebooks = dict(getattr(cur, "NOTEBOOKS", {}) or {})
        own_routes = [tuple(r) for r in (getattr(cur, "OWN_ROUTES", []) or [])]
        ignored = dict(getattr(cur, "IGNORED", {}) or {})

    wanted = [("reminder", f"{project} · reminder (rules + lessons)"),
              (default_label, f"{project} · general")]
    wanted += [(label, f"{project} · {displays[label]}") for label in shared]
    wanted += [(label, f"{project} · {display}") for label, display, _ in own]
    for label, display, prefixes in own:
        for prefix in prefixes:
            if (prefix, label, display) not in own_routes:
                own_routes.append((prefix, label, display))

    to_make = [(label, title) for label, title in wanted if not notebooks.get(label)]
    print(f"Notebooks for {login} (your own Google account):")
    for label, title in wanted:
        state = "new" if (label, title) in to_make else "have it"
        print(f"  {label:<24} {title}   [{state}]")
    if args.dry_run:
        print(f"\n--dry-run: nothing created. Would write {mf.relative_to(VAULT)}.")
        return 0

    auth = subprocess.run(["notebooklm", "auth", "check", "--test"], capture_output=True, text=True)
    if auth.returncode != 0 or "fail" in (auth.stdout + auth.stderr).lower():
        fail("NotebookLM isn't signed in on this computer. Run: notebooklm login (your own Google account)")

    if first_time:
        # Whatever is already in your account isn't this vault's: record it so Roll
        # Call's coverage check doesn't flag your other notebooks.
        for nb in nb_json(["list"]).get("notebooks", []):
            if nb.get("is_owner") is False:
                continue
            ignored.setdefault(nb["id"], f"{(nb.get('title') or '(untitled)').strip()} "
                                         "(in your account before setup; not part of this vault)")

    created = []
    for label, title in to_make:
        nid = nb_json(["create", title])["notebook"]["id"]
        notebooks[label] = nid
        created.append(label)
        print(f"  created {label:<16} {nid}  {title}")
        write_member_file(mf, login, notebooks, own_routes, ignored)   # after EVERY create: nothing orphaned
    write_member_file(mf, login, notebooks, own_routes, ignored)
    print(f"\nWrote {mf.relative_to(VAULT)}")

    default_only = {"reminder": "reminder", default_label: "wiki"}

    def pages_wanted(label):
        if label == "reminder":
            return len((nbm.get("reminder") or {}).get("files", []))
        r = subprocess.run([sys.executable, str(REFRESH), "--count-routed", label],
                           capture_output=True, text=True)
        return int((r.stdout or "0").strip() or 0)

    def pages_recorded(label):
        _nb, state_dir, _info = lm.resolve(VAULT)
        sf = state_dir / f".notebooklm-{label}-state.json"
        return (len(json.loads(sf.read_text())) if sf.exists() else 0), sf.exists()

    # Fill every notebook that is new OR still short of pages — so a run that was cut
    # off part way picks up where it stopped when you run the same command again.
    to_fill = [label for label in notebooks if label in created or pages_recorded(label)[0] < pages_wanted(label)]
    if args.no_fill or not to_fill:
        print("Nothing to fill: every notebook has all its pages." if not to_fill else
              "--no-fill: run this command again without --no-fill when you're ready to upload.")
        return 0

    failed = []
    for label in to_fill:
        only = default_only.get(label, label)
        _have, has_state = pages_recorded(label)
        print(f"\n── filling {label} ──", flush=True)
        # --seed only on a first fill: it maps what's already in the notebook to the
        # files. On a resume the upload records already exist and the refresh adds
        # only what's missing.
        for extra in ((["--seed"], []) if not has_state else ([],)):
            r = subprocess.run([sys.executable, "-u", str(REFRESH), *extra, "--only", only])
            if r.returncode != 0:
                failed.append(f"{label} ({'seed' if extra else 'upload'} exit {r.returncode})")
                break

    # Prove it: every page routed to each notebook is recorded, and every recorded
    # upload is really in its notebook. A refresh can finish with verify/upload
    # failures and still exit 0, so its exit code alone is not proof.
    for label in notebooks:
        want = pages_wanted(label)
        have, _ = pages_recorded(label)
        mark = "ok" if have >= want else "MISSING"
        print(f"  {label:<16} {have} of {want} pages uploaded  [{mark}]")
        if have < want:
            failed.append(f"{label} ({want - have} page(s) not uploaded; run this command again)")
    tracked = subprocess.run([sys.executable, str(REFRESH), "--check-tracked", "--skip-auth-check"],
                             capture_output=True, text=True)
    if tracked.returncode != 0:
        failed.append("some recorded uploads are not in their notebook: "
                      + (tracked.stdout or tracked.stderr).strip()[:300])
    print("\n" + ("All notebooks filled and checked." if not failed else f"Problems: {'; '.join(failed)}"))
    print(f"Next: python3.11 tools/limitless_member.py (your notebooks), run Roll Call, then commit "
          f"members/{login}/ (your agent asks you first).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
