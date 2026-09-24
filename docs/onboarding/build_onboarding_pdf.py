#!/usr/bin/env python3
"""Build Limitless-Stack-Onboarding.pdf — "build your own Limitless Stack".

The guide a new person hands to their own Claude. It describes how the stack is built, so the
reader's agent can build the SAME stack for them — their vault, their notebooks, their index,
their rules. It must never tell a reader to use anyone else's paths, accounts or IDs.

Usage:  python3 build_onboarding_pdf.py [output.pdf]     (default: ../../Limitless-Stack-Onboarding.pdf)
Needs:  reportlab (pip install reportlab). Built-in fonts only (Helvetica/Courier, WinAnsi):
        do not use glyphs outside WinAnsi (no arrows, check marks, command-key symbol).
"""
import os
import sys
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

VERSION = "2.0"
DOC_TITLE = "The Limitless Stack — Onboarding"
FOOTER_LINK = "github.com/Open-Scaffold-Labs/LimitlessStack"

# ── palette (matched to the v1 design) ───────────────────────────────────
COVER_BG = HexColor("#1F1650")
COVER_PANEL = HexColor("#2A1F68")
COVER_PANEL_2 = HexColor("#33287A")
BAND = HexColor("#6D4AE6")
ACCENT = HexColor("#6D4AE6")
NUM = HexColor("#A29BF2")
INK = HexColor("#16132B")
MUTED = HexColor("#5B5775")
RULE = HexColor("#E3E0F2")
CODE_BG = HexColor("#F4F2FC")
CODE_LINE = HexColor("#CFC8F4")
CALL_BG = HexColor("#EEE9FD")
TH_BG = HexColor("#2E2470")

W, H = letter
LM = RM = 0.85 * inch
CW = W - LM - RM

# ── styles ────────────────────────────────────────────────────────────────
def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10, leading=14.2, textColor=INK, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)

body = S("body", spaceAfter=6)
body_s = S("body_s", fontSize=9, leading=12.6, textColor=MUTED, spaceAfter=4)
lead = S("lead", fontSize=11, leading=16, spaceAfter=8)
h2 = S("h2", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=HexColor("#3A2C9A"),
       spaceBefore=10, spaceAfter=5, keepWithNext=1)
h3 = S("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=2, spaceAfter=3)
bullet = S("bullet", leftIndent=14, bulletIndent=2, spaceAfter=3)
cell = S("cell", fontSize=8.8, leading=11.8)
cell_b = S("cell_b", fontName="Helvetica-Bold", fontSize=8.8, leading=11.8)
cell_h = S("cell_h", fontName="Helvetica-Bold", fontSize=8.8, leading=11.8, textColor=white)
code_st = S("code", fontName="Courier", fontSize=8.3, leading=11)
call_st = S("call", fontSize=9.6, leading=13.6)

def P(t, st=body):
    return Paragraph(t, st)

def mono(t):
    return f'<font face="Courier" size="8.8">{escape(t)}</font>'

def bullets(items):
    return [Paragraph(t, bullet, bulletText="\u2022") for t in items]

# ── building blocks ───────────────────────────────────────────────────────
class SectionHead(Flowable):
    """Big light number, title, subtitle, short accent rule — the v1 section header."""
    def __init__(self, num, title, sub):
        super().__init__()
        self.num, self.title, self.sub = num, title, sub
        self.height = 78

    def wrap(self, aw, ah):
        return aw, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(NUM); c.setFont("Helvetica-Bold", 46)
        c.drawString(0, 26, self.num)
        x = c.stringWidth(self.num, "Helvetica-Bold", 46) + 18
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 21)
        c.drawString(x, 44, self.title)
        c.setFillColor(MUTED); c.setFont("Helvetica", 10)
        c.drawString(x, 28, self.sub)
        c.setStrokeColor(ACCENT); c.setLineWidth(1.6)
        c.line(0, 6, 54, 6)


class StepNum(Flowable):
    def __init__(self, n):
        super().__init__(); self.n = str(n)
    def wrap(self, aw, ah):
        return 20, 20
    def draw(self):
        c = self.canv
        c.setFillColor(ACCENT); c.circle(9, 9, 9, stroke=0, fill=1)
        c.setFillColor(white); c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(9, 5.8, self.n)


def section(num, title, sub):
    return [CondPageBreak(3.4 * inch), Spacer(1, 6), SectionHead(num, title, sub), Spacer(1, 10)]


def code(lines):
    t = Table([[Paragraph("<br/>".join(escape(l).replace(" ", "&nbsp;") for l in lines), code_st)]],
              colWidths=[CW], spaceAfter=6)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                           ("BOX", (0, 0), (-1, -1), 0.6, CODE_LINE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def callout(html):
    t = Table([[Paragraph(html, call_st)]], colWidths=[CW])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CALL_BG),
                           ("LINEBEFORE", (0, 0), (0, -1), 3.2, ACCENT),
                           ("BOX", (0, 0), (-1, -1), 0.6, CODE_LINE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return KeepTogether([Spacer(1, 4), t, Spacer(1, 8)])


def table(head, rows, widths):
    data = [[Paragraph(h, cell_h) for h in head]]
    for r in rows:
        data.append([Paragraph(r[0], cell_b)] + [Paragraph(x, cell) for x in r[1:]])
    t = Table(data, colWidths=[w * CW for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), TH_BG),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#FAF9FE")]),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5)]))
    return t


def step(n, title, parts):
    head = Table([[StepNum(n), Paragraph(title, h3)]], colWidths=[26, CW - 26])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    first = parts[0] if parts else Spacer(1, 1)
    return [Spacer(1, 6), KeepTogether([head, first])] + list(parts[1:])


def check(t):
    return P(f"<b>Check:</b> {t}", body_s)

# ── page decoration ───────────────────────────────────────────────────────
def draw_cover(c, doc):
    c.saveState()
    c.setFillColor(COVER_BG); c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(COVER_PANEL); c.rect(0.3 * inch, 0.95 * inch, W - 0.6 * inch, H - 1.25 * inch, stroke=0, fill=1)
    c.setFillColor(COVER_PANEL_2); c.rect(1.3 * inch, 1.5 * inch, W - 2.3 * inch, H - 3.2 * inch, stroke=0, fill=1)
    cx, cy = W - 2.55 * inch, H - 2.35 * inch
    c.setStrokeColor(HexColor("#8C7FF0")); c.setLineWidth(1.1)
    for i in range(8):
        import math
        a = math.pi / 4 * i + math.pi / 8
        c.line(cx + 68 * math.cos(a), cy + 68 * math.sin(a), cx + 92 * math.cos(a), cy + 92 * math.sin(a))
    for r, col in ((58, "#4B3AA8"), (40, "#7563E6"), (26, "#A99CF5"), (15, "#FFFFFF")):
        c.setFillColor(HexColor(col)); c.circle(cx, cy, r, stroke=0, fill=1)
    c.setFillColor(HexColor("#B7ABFF")); c.setFont("Helvetica-Bold", 9)
    c.drawString(0.8 * inch, H - 1.05 * inch, f"ONBOARDING GUIDE  \u00b7  v{VERSION}")
    c.setFillColor(white); c.setFont("Helvetica-Bold", 44)
    c.drawString(0.8 * inch, H - 3.35 * inch, "The Limitless")
    c.drawString(0.8 * inch, H - 3.95 * inch, "Stack")
    c.setFont("Helvetica", 14); c.setFillColor(HexColor("#DAD5FF"))
    c.drawString(0.8 * inch, H - 4.6 * inch, "Seven tools, one operating system.")
    c.drawString(0.8 * inch, H - 4.87 * inch, "Built by you, for you — on your own accounts.")
    c.setFillColor(BAND); c.rect(0, 0, W, 0.62 * inch, stroke=0, fill=1)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 8.5)
    c.drawString(0.8 * inch, 0.26 * inch, f"Open Scaffold Labs  \u00b7  {FOOTER_LINK}")
    c.restoreState()


def draw_page(c, doc):
    c.saveState()
    c.setFillColor(BAND); c.rect(0, H - 9, W, 9, stroke=0, fill=1)
    c.setStrokeColor(RULE); c.setLineWidth(0.6); c.line(LM, 0.62 * inch, W - RM, 0.62 * inch)
    c.setFillColor(MUTED); c.setFont("Helvetica", 7.5)
    c.drawString(LM, 0.45 * inch, DOC_TITLE)
    c.drawRightString(W - RM, 0.45 * inch, str(doc.page))
    c.restoreState()

# ── content ───────────────────────────────────────────────────────────────
def content():
    f = [NextPageTemplate("body"), PageBreak()]

    # 00 ─ Welcome
    f += section("00", "Welcome", "What you'll build, and how to use this guide")
    f += [P("The Limitless Stack is seven tools wired into one operating system for working with "
            "a coding agent: <b>Claude · CLAUDE.md · Obsidian · NotebookLM · Pinecone · Hub Workspace · "
            "Paperclip</b>. It gives your agent a memory it reads <i>and</i> writes, rules it follows "
            "every session, and rituals that make it smarter every time you use it.", lead),
          P("This guide shows you how to build <b>your own</b> copy. You get the same structure, the "
            "same tools and the same rituals as the reference stack. Everything inside it is yours: "
            "your vault, your notes, your notebooks, your index, your rules. Nothing is shared with "
            "anyone else's stack, and nothing here points at anyone else's accounts. (A team can also keep one "
            "shared vault; section 08 shows how.)")]
    f.append(callout("<b>Hand this PDF to your coding agent.</b> Claude Code, the Claude desktop app with a folder "
                     "on your computer connected, or any other coding agent that can read files and run "
                     "commands on your computer. Attach this file and "
                     "say: <i>\"Set up my own Limitless Stack by following this guide. Ask me for my "
                     "details first.\"</i> Your agent interviews you, runs the commands on your computer, "
                     "and checks each step before moving on. You can also follow it by hand."))
    f.append(P("Your details — what your agent will ask you first", h2))
    f.append(table(["Detail", "Used for", "Example"], [
        ["Your name", "The [YOUR NAME] markers in your CLAUDE.md", "Sam"],
        ["Your GitHub account", "Where your vault's private repo lives", "sam-rivera"],
        ["A short project ID", "Your vault, notebook names and Pinecone index", "sam-research"],
        ["Where your vault lives", "The folder everything is built in", "~/sam-research"],
        ["Your domain", "What the wiki tracks", "\"my consulting clients\""],
        ["Your Google account", "Your NotebookLM notebooks", "the account you sign in with"],
        ["Pinecone (optional)", "Semantic search over your files", "a free account + API key"],
        ["How you want to work", "The working rules in your CLAUDE.md", "\"always ask before pushing\""],
    ], [0.24, 0.43, 0.33]))
    f += [Spacer(1, 8), P("By the end you'll have", h2)]
    f += bullets([
        "A <b>wiki vault</b> in Obsidian that your agent maintains: every source you add updates many pages.",
        "<b>Your own NotebookLM notebooks</b>, including a reminder notebook your agent reads at the start of every session.",
        "<b>Mechanical rituals:</b> Roll Call checks the stack before work; an end-of-session checklist leaves it clean.",
        "An <b>anti-patterns ledger</b> — your agent's record of mistakes not to repeat — seeded with twelve starter lessons.",
        "<b>Seven skills</b> for Claude (the same steps are written out for any other agent), and optional semantic search (Pinecone) over your own files.",
    ])

    # 01 ─ The seven tools
    f += section("01", "The seven tools", "Each plays one role. The protocol is how they connect.")
    f.append(table(["Tool", "Role", "In your stack"], [
        ["Claude", "Reasoning engine", "Claude or any coding agent you use: reads, writes, connects, decides"],
        ["CLAUDE.md", "Identity + rules", "Your vault's operating manual — the trust anchor. Required."],
        ["Obsidian", "Knowledge base", "Your wiki: sources, entities, concepts, syntheses. Required."],
        ["NotebookLM", "Research desk + reminder layer", "Your notebooks, declared in your manifest. Required."],
        ["Pinecone", "Semantic memory", "Your index over your files and repos. Optional."],
        ["Hub Workspace", "Shared agent workspace", "For teams that run a Hub. Optional."],
        ["Paperclip", "Agent coordination", "Org chart, budgets, tickets for agents. Optional."],
    ], [0.2, 0.28, 0.52]))
    f += [Spacer(1, 8), P("The three problems it solves", h2),
          P("<b>Amnesia.</b> Every agent session starts cold, and long contexts get expensive and "
            "unreliable. The stack gives your agent a persistent memory it can read and write — the wiki, "
            "NotebookLM and (optionally) Pinecone — so knowledge compounds instead of evaporating."),
          P("<b>Drift.</b> Rules and lessons written in files get ignored unless something enforces "
            "them. The stack enforces them three ways: a mandatory first-action banner in CLAUDE.md, "
            "skills that trigger on your greeting, and a Roll Call script that mechanically gates work."),
          P("<b>Repair at scale.</b> Once you run several apps, manual bug triage doesn't scale. The "
            "optional self-healing loop diagnoses bugs, drafts fixes in a sandbox and opens pull "
            "requests for you to review.")]

    # 02 ─ The flywheel
    f += section("02", "The flywheel", "Four loops that make the stack smarter every time you use it")
    for t, d in [
        ("Loop 1 — Source ingest.", "Drop a source in <font face='Courier'>raw/</font>. Your agent reads it, writes a source "
         "page, updates every entity and concept it touches, and flags contradictions. The more you "
         "ingest, the more cross-references the next ingest can make."),
        ("Loop 2 — Wiki refinement.", "Contradictions are flagged, never silently overwritten. Good "
         "answers are filed back as synthesis pages. A periodic lint catches orphans, broken links and "
         "stale claims."),
        ("Loop 3 — Index sync.", "The end-of-session checklist refreshes your NotebookLM notebooks and "
         "<b>verifies the content landed</b>, and syncs Pinecone if you use it. Every session's wiki edits reach "
         "your notebooks before the session closes."),
        ("Loop 4 — Anti-patterns + reminder notebook.", "When your agent repeats a mistake, it becomes a "
         "numbered entry in your anti-patterns page. That page lives in your reminder notebook, so the "
         "next session reads the lesson before doing anything."),
    ]:
        f.append(P(f"<b>{t}</b> {d}"))

    # 03 ─ Compounding
    f += section("03", "What compounding looks like", "Measured numbers from the reference vault")
    f.append(P("These are the real counts from the vault the stack was built in, read from its git "
               "history on 2026-09-23. Your numbers will differ — they depend on how much you ingest — "
               "but the shape is the point: pages and lessons keep accumulating, session after session."))
    f.append(table(["", "Your day 1", "Day ~30", "Day ~90", "Day 161"], [
        ["Wiki pages", "8 starter pages", "81", "104", "160"],
        ["Anti-patterns", "12 starter lessons", "16", "29", "79"],
        ["NotebookLM notebooks", "2 (yours)", "", "", "8 routed"],
        ["Pinecone vectors", "0 (optional)", "", "", "34,506"],
    ], [0.24, 0.22, 0.18, 0.18, 0.18]))
    f.append(Spacer(1, 6))
    f.append(callout("<b>If your numbers stop moving, the loop has a leak</b> — almost always a skipped "
                     "end-of-session step. Roll Call exists to catch those leaks at the start of the "
                     "next session."))

    # 04 ─ Self-healing
    f += section("04", "Self-healing (optional)", "Autonomous bug repair, with you approving every merge")
    f.append(P("Once your stack is running, you can let Claude repair bugs in your own apps. It is "
               "opt-in and off by default: you add it to one app repo at a time from the templates in "
               "<font face='Courier'>self-heal/templates/</font> (the installer also copies them into "
               "<font face='Courier'>self-heal-templates/</font> in your vault)."))
    steps10 = [
        ("Capture", "A user reports a bug in your app; description + context are posted to your bug-report endpoint."),
        ("Diagnose", "Claude, with your CLAUDE.md as its rules, writes a diagnosis: severity, root cause, suspected files."),
        ("Review", "You read the diagnosis and decide whether to dispatch a repair."),
        ("Dispatch", "A GitHub repository_dispatch event starts the repair workflow."),
        ("Init", "A GitHub Actions runner checks out a branch. Sandboxed — never production."),
        ("Investigate", "The agent works with a fixed tool list and a 25-turn budget."),
        ("Commit", "If it changed code it commits; if not, it reports why."),
        ("PR", "It opens a pull request with the full context."),
        ("Merge", "You review. Auto-merge is off by default."),
        ("Reconcile", "The bug record is updated; new failure patterns go into your anti-patterns page."),
    ]
    f.append(table(["#", "Stage", "What happens"], [[str(i + 1), a, b] for i, (a, b) in enumerate(steps10)],
                   [0.06, 0.16, 0.78]))
    f += [Spacer(1, 8), P("Five rules that make it trustworthy", h2)]
    f += bullets([
        "<b>CLAUDE.md is the trust anchor</b> — both agents run with it as their rules.",
        "<b>Diagnose before repair</b> — the cheap pass always runs first; repair is gated by you.",
        "<b>Sandboxed execution</b> — an ephemeral runner with a code-enforced tool list.",
        "<b>Human merge by default</b> — pull requests, never direct commits.",
        "<b>Closed-loop audit</b> — every transition is recorded on the bug record.",
    ])

    # 05 ─ Skills + tools
    f += section("05", "Seven skills, plus the tools", "Installed by install.sh")
    f.append(P("Skills are Claude's format: a Markdown file Claude loads when its description matches what you're doing. "
               "The installer puts all seven in <font face='Courier'>~/.claude/skills/</font> (read by Claude "
               "Code). In the Claude desktop app, add skills under <b>Settings, Capabilities</b>. Other agents don't load "
               "skills; everything the skills do is also written out in your CLAUDE.md and the tools."))
    f.append(table(["Skill", "What it does", "When it triggers"], [
        ["roll-call", "Runs tools/limitless-preflight.sh in your vault and reports READY / WARN / BLOCK.",
         "\"hey claude\", \"roll call\", \"are you ready\", session start"],
        ["limitless-stack", "The umbrella protocol: lookup order, first action, end-of-session checklist.",
         "Work in a Limitless Stack vault"],
        ["notebooklm", "Full NotebookLM CLI: notebooks, sources, questions, generated artifacts.",
         "Any NotebookLM operation"],
        ["audit-before-claim", "Verify before stating: done, fixed, counts, \"unavailable\".",
         "About to claim a result or report status"],
        ["karpathy-guidelines", "Code-edit discipline: think first, keep it simple, surgical changes.",
         "Writing or reviewing code"],
        ["impeccable", "Frontend design: shape, critique, audit and polish interfaces.",
         "Designing or improving a UI"],
        ["of-module-hardening", "A hardening checklist written for one specific app codebase.",
         "Only that codebase — safe to ignore"],
    ], [0.22, 0.48, 0.30]))
    f += [Spacer(1, 8), P("The tools in your vault's tools/ folder", h2)]
    f.append(table(["Tool", "Purpose"], [
        ["limitless-preflight.sh", "Roll Call itself: checks the stack, exit 0 / 1 / 2"],
        ["session-bootstrap.sh", "Session-start snapshot: wiki state, recent log entries, open items"],
        ["notebooklm-wiki-refresh.py", "Mirrors wiki pages to your notebooks and verifies they landed"],
        ["notebooklm-dedupe.py", "Finds and removes duplicate notebook sources"],
        ["recall.sh", "Searches your decision history before you call something missing"],
        ["pinecone-sync.py / -search.py", "Index and search your files (optional)"],
        ["nightly-selfheal.sh", "Optional nightly run: Roll Call, then only the safe automatic fixes (notebook refresh, Pinecone sync), then re-check"],
        ["authorship-guard.py", "Shared vaults only: stops a commit that changes someone else's writing (section 08)"],
    ], [0.34, 0.66]))

    # 06 ─ Enforcement
    f += section("06", "Enforcement", "Three layers that make the rituals reliable")
    f.append(P("<b>Layer 1 — the banner at the top of your CLAUDE.md.</b> Claude reads CLAUDE.md "
               "automatically when a session opens in your vault; your vault's AGENTS.md points every other "
               "coding agent to the same file. It starts with:"))
    f.append(code(["MANDATORY FIRST ACTION - NO EXCEPTIONS",
                   "1. Invoke the roll-call skill. (0 = READY, 1 = WARN, 2 = BLOCK)",
                   "2. Run bash tools/session-bootstrap.sh",
                   "3. Query this vault's reminder notebook (through the notebooklm skill)",
                   "4. Read wiki/index.md",
                   "5. Do NOT skip these steps",
                   "6. Do NOT answer from active context alone. Verify and cite."]))
    f.append(P("<b>Layer 2 — skills that trigger on your greeting (Claude).</b> The roll-call skill lists "
               "phrases like \"hey claude\" and \"roll call\", so saying hello starts the check even if the "
               "banner were missed. With other agents, Layer 3 does this job."))
    f.append(P("<b>Layer 3 — an explicit prompt, when you want to be sure:</b>"))
    f.append(code(["Run roll call, then the session bootstrap, then ask my reminder notebook",
                   "for my current rules and recent lessons. Then read wiki/index.md."]))
    f.append(P("The end of a session works the same way. The most reliable phrase is <i>\"Run the "
               "end-of-session checklist.\"</i> The two rituals check each other: if a wrap-up was "
               "skipped, the next Roll Call flags the uncommitted work."))

    # 07 ─ Build your stack
    f += section("07", "Build your stack", "Each step ends with a check. Replace every <...> with your details.")
    f.append(P("<b>You need:</b> a Mac with Homebrew, Python 3.11 (<font face='Courier'>brew install "
               "python@3.11</font>), git and the GitHub CLI (<font face='Courier'>gh auth login</font>), "
               "Obsidian, a coding agent (Claude or another agent that can run commands on your computer), and a Google "
               "account. Pinecone is optional."))
    f += step(1, "Get the Limitless Stack", [
        code(["git clone https://github.com/Open-Scaffold-Labs/LimitlessStack.git ~/LimitlessStack",
              "echo 'export LIMITLESS_STACK_HOME=~/LimitlessStack' >> ~/.zshrc && source ~/.zshrc"]),
        check("<font face='Courier'>ls ~/LimitlessStack</font> shows bin/, tools/, skills/, templates/ and install.sh."),
    ])
    f += step(2, "Create your vault", [
        P("This writes your vault, your CLAUDE.md, your wiki starter pages and your manifest "
          "(<font face='Courier'>.limitless-project.py</font>) — the one file that names your notebooks and index."),
        KeepTogether([code(["~/LimitlessStack/bin/limitless-stack-init <project-id> <vault-path> --description \"<your domain>\""]),
        check("the vault folder contains CLAUDE.md, AGENTS.md, .limitless-project.py, tools/ and wiki/.")]),
    ])
    f += step(3, "Install the skills and tools", [
        code(["~/LimitlessStack/install.sh <vault-path>"]),
        P("It installs the Python packages and the browser used for NotebookLM sign-in, the seven skills, "
          "and the tools. It prints two commands for the optional nightly job; nothing runs on a "
          "schedule unless you run them."),
        check("<font face='Courier'>ls ~/.claude/skills/</font> lists seven skills."),
    ])
    f += step(4, "Create your NotebookLM notebooks", [
        code(["notebooklm login                       # your Google account, in a browser, once",
              "notebooklm create \"<project-id>\"",
              "notebooklm create \"<project-id> Reminder\""]),
        P("Copy each returned ID into <font face='Courier'>&lt;vault-path&gt;/.limitless-project.py</font>: the first "
          "replaces <font face='Courier'>REPLACE_WITH_NEW_NOTEBOOK_ID</font>, the second "
          "<font face='Courier'>REPLACE_WITH_REMINDER_NOTEBOOK_ID</font>. Then fill them:"),
        code(["cd <vault-path>",
              "python3.11 tools/notebooklm-wiki-refresh.py --seed",
              "python3.11 tools/notebooklm-wiki-refresh.py"]),
        P("On brand-new notebooks the seed warns that two curated files have no match yet. That is "
          "expected: the refresh right after it adds them.", body_s),
        check("the refresh reports <b>verify_failed: 0</b> and <b>upload_failed: 0</b>."),
    ])
    f += step(5, "Make CLAUDE.md yours", [
        P("Your CLAUDE.md has <b>[YOUR ...]</b> markers: your name, your domain, your working rules, your "
          "notes. Let your agent interview you and fill every one, then write "
          "<font face='Courier'>wiki/overview.md</font> — your current thesis, in your own words."),
        check("<font face='Courier'>grep -c \"\\[YOUR\" CLAUDE.md</font> prints 0."),
    ])
    f += step(6, "Put your vault on GitHub", [
        code(["cd <vault-path> && git init && git add -A && git commit -m \"initial commit\"",
              "gh repo create <your-github-account>/<project-id> --private --source . --push"]),
        check("<font face='Courier'>git status</font> is clean and the repo shows on GitHub."),
    ])
    f += step(7, "Pinecone (optional)", [
        P("Create a free account at pinecone.io and an API key. Store the key in your Keychain, then "
          "create an index with Pinecone's hosted embedding model:"),
        code(["security add-generic-password -a pinecone -s pinecone-api-key -U -w   # paste the key",
              "python3.11 -c 'import subprocess; from pinecone import Pinecone; \\",
              "  k=subprocess.run([\"security\",\"find-generic-password\",\"-s\",\"pinecone-api-key\",\"-w\"],",
              "    capture_output=True,text=True,check=True).stdout.strip(); \\",
              "  Pinecone(api_key=k).create_index_for_model(name=\"<project-id>\", cloud=\"aws\",",
              "    region=\"us-east-1\", embed={\"model\":\"multilingual-e5-large\",",
              "    \"field_map\":{\"text\":\"chunk_text\"}})'"]),
        P("Your manifest already names the index after your project ID. Add <font face='Courier'>\"pinecone\"</font> "
          "to <font face='Courier'>CHECKS</font> in it, put any repos you want searchable in "
          "<font face='Courier'>raw/repos/</font>, then run "
          "<font face='Courier'>python3.11 tools/pinecone-sync.py</font>. The free plan caps embedding at "
          "5 million tokens a month; if the sync reports that limit, wait for the monthly reset or upgrade."),
        check("<font face='Courier'>python3.11 tools/pinecone-search.py \"a test question\"</font> returns hits."),
    ])
    f += step(8, "Run Roll Call", [
        P("Open your agent in your vault and say <i>\"roll call\"</i> (or run "
          "<font face='Courier'>bash tools/limitless-preflight.sh</font>). Work through anything it reports "
          "until it says <b>READY</b>, or <b>WARN</b> with only warnings you choose to accept."),
    ])
    f.append(callout("<b>Your first Roll Call will not be green, and that's expected.</b> Until you've "
                     "signed in to NotebookLM it reports BLOCK. Until your notebooks are created and "
                     "refreshed, and your overview is written, it lists those as warnings. Every one maps "
                     "to a step above. Your vault's <font face='Courier'>wiki/team-tasks.md</font> holds the "
                     "same checklist so your agent can tick it off."))

    # 08 ─ Operating
    f += section("08", "Operating", "Day-to-day moves that keep the loop alive")
    for t, d in [
        ("Start every session", "Say \"roll call\" (Claude also answers to \"hey claude\"). Your agent checks the stack, reads your reminder notebook and the index."),
        ("Ingest a source", "Drop it in raw/ and say \"Ingest the new source at raw/<file>\"."),
        ("Ask a question", "Just ask. Your agent follows the lookup order and cites your wiki. Good answers get filed as synthesis pages."),
        ("Lint", "Every few weeks: \"Run a lint pass and write the report.\""),
        ("Catch a new mistake", "Ask your agent to add it to wiki/synthesis/claude-anti-patterns.md as the next numbered entry."),
        ("End every session", "\"Run the end-of-session checklist.\" Tasks ticked, log appended, repos pushed, notebooks refreshed and verified."),
        ("Get improvements", "git -C ~/LimitlessStack pull, then re-run install.sh on your vault. It refreshes tools and skills; your CLAUDE.md, manifest and wiki are never overwritten."),
    ]:
        f.append(P(f"<b>{t}.</b> {escape(d)}"))
    f += [P("Make it yours — the checklist", h2)]
    f += bullets([
        "<b>Your manifest</b> (.limitless-project.py): your notebook IDs, your Pinecone index, which optional checks run.",
        "<b>Your CLAUDE.md</b>: every [YOUR ...] marker filled; edit it whenever a convention stops working.",
        "<b>Your wiki</b>: your overview, your sources, your entities. The starter pages are yours to change.",
        "<b>Your lessons</b>: add your own anti-patterns after the twelve starters. Never renumber.",
        "<b>Keep as-is</b>: the tools and skills (update them with git pull + install.sh), the first-action banner, the end-of-session checklist.",
    ])
    f += [P("Sharing a vault with teammates (optional)", h2)]
    f.append(P("A vault can be one team's shared record: everyone reads everything and adds freely, but "
               "each person's writing can only be changed by that person. Anyone else who wants a change "
               "sends the owner a suggestion; the owner approves it and makes the change. Skip this for a "
               "vault only you write to."))
    f.append(P("<b>1. Turn on the rule.</b> Copy <font face='Courier'>~/LimitlessStack/templates/authors.example.json</font> "
               "to <font face='Courier'>.authors.json</font> at the vault root and list each person's GitHub "
               "login with every email they commit with. In <font face='Courier'>.limitless-project.py</font> set "
               "<font face='Courier'>VAULT_OWNER = \"&lt;your-login&gt;\"</font>: the vault's upkeep checks then run on "
               "your Roll Call, and each teammate's Roll Call shows only their own machine, sign-ins and task file. "
               "Commit both."))
    f.append(P("<b>2. Each person, on their own computer:</b> clone the vault, then run "
               "<font face='Courier'>bash tools/install-git-hooks.sh</font>. From then on a commit that changes "
               "someone else's lines, their <font face='Courier'>members/&lt;login&gt;/</font> folder or their "
               "<font face='Courier'>wiki/my-tasks/&lt;login&gt;.md</font> is refused, and the message says how to "
               "send a suggestion instead."))
    f.append(P("<b>3. Personal rules.</b> Each person keeps their own agent instructions in "
               "<font face='Courier'>members/&lt;login&gt;/CLAUDE.md</font>, which everyone can read."))
    f.append(P("<b>4. Optional backstop.</b> Copy <font face='Courier'>templates/github/authorship-safety-net.yml</font> "
               "to <font face='Courier'>.github/workflows/</font>. Each night it checks the day's commits and "
               "opens an issue for anyone whose writing was changed without the check, so they decide. "
               "Run it once by hand to prove it works."))
    f.append(check("<font face='Courier'>bash tools/test-authorship-guard.sh</font> ends with \"0 failed\"."))

    # 09 ─ Troubleshooting
    f += section("09", "Troubleshooting", "What Roll Call and the tools tell you, and what to do")
    f.append(table(["You see", "Do this"], [
        ["BLOCK: NotebookLM auth failing", "Run notebooklm login on your computer, then notebooklm auth check --test."],
        ["\"No Pinecone index configured\"", "Add PINECONE = {\"index\": \"<your-index>\"} to .limitless-project.py (step 7)."],
        ["Notebook coverage warning", "Every notebook in your Google account must be in your manifest: a route, the default, the reminder, or \"ignored\"."],
        ["verify_failed above 0", "The upload didn't land. Delete that source in the notebook and add the file again; don't just re-run."],
        ["A refresh seemed to time out", "Check the notebook before retrying — large files take minutes to index."],
        ["Tools out of sync with LimitlessStack", "You edited a tool in one place. Copy it to the other, or re-run install.sh."],
        ["overview.md placeholder warning", "Write your overview and give it real dates (step 5)."],
        ["Your agent can't run notebooklm", "It must run on your own computer, where you signed in — not inside a cloud sandbox."],
    ], [0.36, 0.64]))
    f.append(Spacer(1, 14))
    f.append(P("The Limitless Stack is one integrated system: the value compounds across all seven "
               "tools, every session, every source and every lesson. The stack you run on day 90 won't be "
               "the one you started with — that's the point.", S("closing", fontName="Helvetica-Oblique",
                                                                 fontSize=10, leading=14.5, textColor=HexColor("#3A2C9A"))))
    return f


def build(out):
    doc = BaseDocTemplate(out, pagesize=letter, title="The Limitless Stack — Onboarding",
                          author="Open Scaffold Labs", subject=f"Onboarding guide v{VERSION}",
                          leftMargin=LM, rightMargin=RM, topMargin=0.85 * inch, bottomMargin=0.85 * inch)
    cover = Frame(0, 0, W, H, id="cover")
    frame = Frame(LM, 0.85 * inch, CW, H - 1.7 * inch, id="body")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[cover], onPage=draw_cover),
                          PageTemplate(id="body", frames=[frame], onPage=draw_page)])
    doc.build([Spacer(1, 1)] + content())


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "..", "Limitless-Stack-Onboarding.pdf")
    build(out)
    print("wrote", os.path.abspath(out))
