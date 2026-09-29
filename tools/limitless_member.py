#!/usr/bin/env python3
"""limitless_member.py — each person's OWN NotebookLM notebooks in a shared vault.

In a vault shared by several people (.authors.json at the root, VAULT_OWNER in
.limitless-project.py), the manifest's NOTEBOOKLM block names the OWNER's notebooks.
Every other member keeps notebooks of their own in their own Google account, declared
in members/<login>/notebooklm.py — a file only they can change (the authorship rule):

    NOTEBOOKS = {                      # label -> notebook id, in YOUR Google account
        "reminder": "<id>",            # the rules + lessons (the vault's reminder files)
        "wiki": "<id>",                # the vault pages that belong to no project
        "openfirehouse": "<id>",       # a project you share with the owner (same label)
        "my-app": "<id>",              # a project of your own (see OWN_ROUTES)
    }
    OWN_ROUTES = [("wiki/apps/my-app.md", "my-app", "My App")]   # your projects' pages
    IGNORED = {"<id>": "why"}          # notebooks in your account that are not this vault's

apply() turns the vault's NOTEBOOKLM block into that person's view:
  * a vault route whose label you have a notebook for  -> your notebook
  * a vault route whose label you do NOT carry         -> skipped: those pages are
    uploaded nowhere for you (never dumped into your general notebook)
  * OWN_ROUTES                                         -> your projects, matched first
  * the default bucket and the reminder notebook       -> yours; same files as the vault's
  * upload records                                     -> members/<login>/notebooklm-state/
The owner, a personal vault, or an identity that can't be read get the block
UNCHANGED (fail-open to how the tools worked before 2026-09-24).

Roles returned in info["role"]:
  owner   the block as the manifest has it; records in tools/
  member  a teammate with members/<login>/notebooklm.py
  unset   a teammate without one yet: NO notebooks — the tools must not fall back
          to the owner's (run tools/notebooklm-member-setup.py)

CLI:  python3.11 tools/limitless_member.py      who you are here, and your notebook ids
"""
import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_py(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def runner(vault, owner):
    """(login, is_teammate). Fail-open: rule off, no owner named, no commit email,
    or anything unreadable -> ("", False), i.e. treated as the owner."""
    vault = Path(vault)
    if not owner or not (vault / ".authors.json").exists():
        return "", False
    guard = vault / "tools" / "authorship-guard.py"
    if not guard.exists():
        return "", False
    try:
        email = subprocess.run(["git", "-C", str(vault), "config", "user.email"],
                               capture_output=True, text=True).stdout.strip()
        if not email:
            return "", False
        g = _load_py(guard, "_lm_authorship_guard")
        cfg = g.load_config(str(vault))
        if cfg is None:
            return "", False
        login = g.person_for(email, cfg)
    except Exception:
        return "", False
    return login, login != owner


def member_file(vault, login):
    return Path(vault) / "members" / login / "notebooklm.py"


def member_state_dir(vault, login):
    return Path(vault) / "members" / login / "notebooklm-state"


def apply(vault, nb, owner):
    """Return (notebooklm_block_for_this_person, state_dir, info).
    Raises ValueError when a member's own file is present but unusable."""
    vault = Path(vault)
    nb = dict(nb or {})
    login, teammate = runner(vault, owner)
    if not teammate:
        return nb, vault / "tools", {"login": login, "role": "owner"}
    mf = member_file(vault, login)
    if not mf.exists():
        return {}, member_state_dir(vault, login), {"login": login, "role": "unset"}
    try:
        m = _load_py(mf, "_lm_member_notebooks")
    except Exception as e:
        raise ValueError(f"{mf.relative_to(vault)} could not be read: {e}")
    mine = dict(getattr(m, "NOTEBOOKS", {}) or {})
    own = list(getattr(m, "OWN_ROUTES", []) or [])
    default = nb.get("default") or ("", "wiki", "wiki")
    for need in ("reminder", default[1]):
        if not mine.get(need):
            raise ValueError(f"{mf.relative_to(vault)}: NOTEBOOKS has no '{need}' notebook")
    order, routes = [], []
    for entry in own:
        prefix, label, display = entry
        if not mine.get(label):
            raise ValueError(f"{mf.relative_to(vault)}: OWN_ROUTES names '{label}' but NOTEBOOKS has no notebook for it")
        r = (prefix, mine[label], label, display)
        order.append(r)
        routes.append(r)
    for prefix, _nbid, label, display in nb.get("routes", []):
        if mine.get(label):
            r = (prefix, mine[label], label, display)
            order.append(r)
            routes.append(r)
        else:
            order.append((prefix, None, None, display))   # a project you don't carry: skipped
    out = dict(nb)
    out["routes"] = routes
    out["routing_order"] = order
    out["default"] = (mine[default[1]], default[1], default[2])
    reminder = dict(nb.get("reminder", {}) or {})
    reminder["notebook_id"] = mine["reminder"]
    out["reminder"] = reminder
    out["ignored"] = dict(getattr(m, "IGNORED", {}) or {})
    return out, member_state_dir(vault, login), {"login": login, "role": "member"}


def load_manifest(vault):
    path = Path(vault) / ".limitless-project.py"
    if not path.exists():
        return None
    return _load_py(path, "_lm_manifest")


def resolve(vault):
    """apply() against the vault's own manifest. No manifest -> owner, tools/."""
    m = load_manifest(vault)
    if m is None:
        return {}, Path(vault) / "tools", {"login": "", "role": "owner"}
    return apply(vault, getattr(m, "NOTEBOOKLM", {}) or {}, getattr(m, "VAULT_OWNER", "") or "")


def main():
    vault = Path(__file__).resolve().parent.parent
    try:
        nb, state_dir, info = resolve(vault)
    except ValueError as e:
        print(f"your notebook file has a problem: {e}")
        return 2
    who = info["login"] or "the vault owner"
    if info["role"] == "unset":
        print(f"You ({who}) have no NotebookLM notebooks of your own for this vault yet.")
        print("Make them: python3.11 tools/notebooklm-member-setup.py --shared <projects you share>")
        return 1
    print(f"Notebooks for {who} ({'your own' if info['role'] == 'member' else 'from the manifest'}):")
    rem = (nb.get("reminder") or {}).get("notebook_id", "")
    if rem:
        print(f"  reminder (rules + lessons)   {rem}")
    if nb.get("default"):
        print(f"  {nb['default'][1]:<28} {nb['default'][0]}   (pages that belong to no project)")
    seen = set()
    for _prefix, nbid, label, _display in nb.get("routes", []):
        if label in seen:
            continue
        seen.add(label)
        print(f"  {label:<28} {nbid}")
    skipped = sorted({o[3] for o in nb.get("routing_order", []) if o[2] is None})
    if skipped:
        print(f"  not carried (never uploaded for you): {', '.join(skipped)}")
    print(f"  upload records: {state_dir.relative_to(vault)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
