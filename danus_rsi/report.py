"""Portable reports. Audit case content is omitted from the rendered summary."""
import html
from pathlib import Path

from .protocol import save_json


def summary(result):
    kind = result.get("kind", "campaign")
    lines = []
    if kind == "benchmark":
        for row in result["rows"]:
            lines.append((row["task_id"], row["domain"], row["decision"]))
    elif kind == "research":
        for item in result["findings"]:
            lines.append((item["task"]["title"], item["task"]["domain"], item["status"]))
    elif kind == "rsi":
        for item in result["cycles"]:
            lines.append((f"Development cycle {item['cycle']}", item["candidate"][:12],
                          "branch selected" if item["selected_for_next_cycle"] == item["candidate"] else "baseline retained"))
    elif kind == "audit":
        lines.append(("Fresh audit evaluation", result["evaluation_id"][:12], "promoted" if result["promoted"] else "not promoted"))
        lines.extend(("Gate", reason, "requires attention") for reason in result["gate"]["reasons"])
    else:
        for section in result.get("rounds", []):
            lines.extend(summary(section["research"]))
            lines.extend(summary(section["improvement"]))
    return lines


def write_report(store, run_id, result):
    run = store.run(run_id)
    result = {"run_id": run_id, "mode": run["manifest"]["mode"], "result": result}
    artifact = store.put("run_result", result)
    folder = store.directory / "reports" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    # Full evidence stays in local state; do not commit this directory or private audits.
    save_json(folder / "report.json", result)
    warning = ("SCRIPTED DEMONSTRATION — no model inference, research results, or measured improvement."
               if result["mode"] != "live" else
               "Experimental model judgments. Informal verification is not formal proof, empirical confirmation, or an independent novelty assessment.")
    rows = summary(result["result"])
    md = ["# Danus RSI research report", "", warning, "", f"Run: `{run_id}`", "",
          f"Calls reserved: {run['calls']} / {run['budget']}", "", "| Item | Domain / version | Outcome |", "|---|---|---|"]
    md += ["| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in row) + " |" for row in rows]
    md += ["", "Inspect report.json and the local calls directory for structured evidence. Audit cases must remain private.", ""]
    (folder / "report.md").write_text("\n".join(md), encoding="utf-8")
    escaped_rows = "".join("<tr>" + "".join("<td>" + html.escape(str(v)) + "</td>" for v in row) + "</tr>" for row in rows)
    content = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Danus RSI research report</title><style>
:root{font-family:system-ui,sans-serif;color:#dce5ee;background:#101a24}body{max-width:1100px;margin:48px auto;padding:0 24px}
h1{font-family:Georgia,serif;font-weight:normal;font-size:42px}p{line-height:1.6}.notice{border-left:4px solid #f2be69;background:#20303c;padding:18px}
.meta{color:#a5bccb}table{width:100%;border-collapse:collapse;margin-top:32px}th{text-align:left;color:#a7d7ce}td,th{padding:15px 10px;border-bottom:1px solid #31414d;vertical-align:top;overflow-wrap:anywhere}
footer{color:#a5bccb;font-size:14px;margin-top:32px}code{overflow-wrap:anywhere}</style><body><p class="meta">DANUS / RESEARCH SYSTEMS</p>
<h1>Research &amp; verifier development</h1><p class="notice">""" + html.escape(warning) + "</p><p class=\"meta\">Run <code>" + run_id + "</code> · " + str(run["calls"]) + " / " + str(run["budget"]) + " calls reserved</p><table><thead><tr><th>Item</th><th>Domain / version</th><th>Outcome</th></tr></thead><tbody>" + escaped_rows + "</tbody></table><footer>Valency: scholarly records and provenance. SQLite: local experimental state. No claims of autonomous scientific discovery. Full evidence is stored locally; audit cases are omitted from this summary.</footer></body></html>"
    (folder / "report.html").write_text(content, encoding="utf-8")
    return {"artifact": artifact, "report": str(folder / "report.html"), "json": str(folder / "report.json")}
