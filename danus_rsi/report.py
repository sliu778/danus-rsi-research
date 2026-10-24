"""Portable reports. Audit case content is omitted from the rendered summary."""
from __future__ import annotations

import html

from .protocol import save_json

HTML_HEAD = (
    '<!doctype html><html lang="en"><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
    "<title>Danus RSI research report</title><style>\n"
    ":root{font-family:system-ui,sans-serif;color:#dce5ee;background:#101a24}"
    "body{max-width:1100px;margin:48px auto;padding:0 24px}\n"
    "h1{font-family:Georgia,serif;font-weight:normal;font-size:42px}p{line-height:1.6}"
    ".notice{border-left:4px solid #f2be69;background:#20303c;padding:18px}\n"
    ".meta{color:#a5bccb}table{width:100%;border-collapse:collapse;margin-top:32px}th{text-align:left;color:#a7d7ce}"
    "td,th{padding:15px 10px;border-bottom:1px solid #31414d;vertical-align:top;overflow-wrap:anywhere}\n"
    "footer{color:#a5bccb;font-size:14px;margin-top:32px}code{overflow-wrap:anywhere}</style>"
    '<body><p class="meta">DANUS / RESEARCH SYSTEMS</p>\n'
    '<h1>Research, verifier &amp; solver development</h1><p class="notice">'
)
HTML_TABLE = "<table><thead><tr><th>Item</th><th>Domain / version</th><th>Outcome</th></tr></thead><tbody>"
HTML_FOOT = (
    "</tbody></table><footer>Valency: scholarly records and provenance. SQLite: local experimental state. "
    "No claims of autonomous scientific discovery. Full evidence is stored locally; "
    "audit cases are omitted from this summary.</footer></body></html>"
)
SCRIPTED_WARNING = "SCRIPTED DEMONSTRATION — no model inference, research results, or measured improvement."
LIVE_WARNING = ("Experimental model judgments. Informal verification is not formal proof, empirical confirmation, "
                "or an independent novelty assessment.")


def interval(ci):
    return f"[{ci[0]:.2f}, {ci[1]:.2f}]" if ci else "[n/a]"


def evidence(kind, gate):
    """The numbers behind a development decision; intervals are descriptive, not the gate."""
    b, c = gate.get("baseline"), gate.get("candidate")
    if not b or not c:
        return ""
    if kind == "solver-rsi":
        return (f"; strict accepts {b['accepted']}/{b['attempts']} {interval(b['solve_rate_95ci'])}"
                f" → {c['accepted']}/{c['attempts']} {interval(c['solve_rate_95ci'])}")
    if b["balanced_accuracy"] is None or c["balanced_accuracy"] is None:
        return "; balanced accuracy n/a (selection lacks valid or invalid cases)"
    return f"; balanced accuracy {b['balanced_accuracy']:.2f} → {c['balanced_accuracy']:.2f}"


def summary(result):
    kind = result.get("kind", "campaign")
    lines = []
    if kind == "benchmark":
        for row in result["rows"]:
            lines.append((row["task_id"], row["domain"], row["decision"]))
    elif kind == "research":
        for item in result["findings"]:
            lines.append((item["task"]["title"], item["task"]["domain"], item["status"]))
    elif kind in ("rsi", "solver-rsi"):
        arm = "Solver" if kind == "solver-rsi" else "Verifier"
        for item in result["cycles"]:
            selected = item["candidate"] is not None and item["selected_for_next_cycle"] == item["candidate"]
            outcome = "branch selected" if selected else "baseline retained"
            lines.append((f"{arm} development cycle {item['cycle']}", (item["candidate"] or "no candidate")[:12],
                          outcome + evidence(kind, item["development_gate"])))
    elif kind == "mining":
        lines.append(("Valency mining", f"{result['papers']} eligible records",
                      f"{len(result['drafts'])} quarantined draft(s), {len(result['rejected'])} rejected"))
    elif kind == "audit":
        arm = "Solver" if result.get("arm") == "solver" else "Verifier"
        lines.append((f"{arm} fresh audit evaluation", result["evaluation_id"][:12],
                      "promoted" if result["promoted"] else "not promoted"))
        lines.extend(("Gate", reason, "requires attention") for reason in result["gate"]["reasons"])
    else:
        for section in result.get("rounds", []):
            lines.extend(summary(section["research"]))
            lines.extend(summary(section["improvement"]))
        if result.get("mining"):
            lines.extend(summary(result["mining"]))
    return lines


def write_report(store, run_id, result):
    run = store.run(run_id)
    result = {"run_id": run_id, "mode": run["manifest"]["mode"], "result": result}
    artifact = store.put("run_result", result)
    folder = store.directory / "reports" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    # Full evidence stays in local state; do not commit this directory or private audits.
    save_json(folder / "report.json", result)
    warning = SCRIPTED_WARNING if result["mode"] != "live" else LIVE_WARNING
    rows = summary(result["result"])
    md = ["# Danus RSI research report", "", warning, "", f"Run: `{run_id}`", "",
          f"Calls reserved: {run['calls']} / {run['budget']}", "",
          "| Item | Domain / version | Outcome |", "|---|---|---|"]
    md += ["| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in row) + " |" for row in rows]
    md += ["", "Inspect report.json and the local calls directory for structured evidence. "
               "Audit cases must remain private.", ""]
    (folder / "report.md").write_text("\n".join(md), encoding="utf-8")
    escaped_rows = "".join("<tr>" + "".join("<td>" + html.escape(str(v)) + "</td>" for v in row) + "</tr>"
                           for row in rows)
    content = (HTML_HEAD + html.escape(warning)
               + f'</p><p class="meta">Run <code>{run_id}</code> · {run["calls"]} / {run["budget"]} calls reserved</p>'
               + HTML_TABLE + escaped_rows + HTML_FOOT)
    (folder / "report.html").write_text(content, encoding="utf-8")
    return {"artifact": artifact, "report": str(folder / "report.html"), "json": str(folder / "report.json")}
