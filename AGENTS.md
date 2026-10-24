Use rigorous, academic explanations and LaTeX for mathematical content.

This repository orchestrates research; software tests may execute code, but research agents must perform mathematics and theoretical physics through textual arguments only. Keep model inference separate from scripted fixtures. Do not call an LLM judgment a formal certificate or a physics derivation empirical validation.

Run `python -m unittest discover -s tests -v` and `python -m danus_rsi demo --state <temporary-directory>` after changes to orchestration. Preserve the frozen promotion rules, audit isolation, resource budgets, provenance, and subscription-only backend. Agent proposals may change strategy text and suggest draft tasks, never evaluation labels or gate code. Each improvement arm changes only its own text: the verifier arm holds solver strategy fixed, the solver arm holds verifier guidance fixed, and the solver optimizer never sees references. Mined drafts stay quarantined until independent review. The Danus bridge writes only through `danus assign` with explicit confirmation and reads verifier outcomes read-only; never write the Danus fact graph or read worker-local memory. Use Valency for scholarly records; do not claim it provides arbitrary application storage.

## Style

Python: every package module starts with a docstring and `from __future__ import annotations`. Imports come in two blocks, standard library then package, each sorted by module name, with no unused names. Use two blank lines between top-level definitions, double quotes unless the text contains one, and at most 120 characters per line; wrap long text with adjacent string literals so the string itself is unchanged. Keep the standard library as the only core dependency. `tests/test_style.py` enforces these rules, and `python scripts/check.py` runs it with the rest of the suite.

Data: JSON is UTF-8 with two-space indentation and a trailing newline. Docs: sentence-case headings, one paragraph per line, a language on every code fence, and `-` for bullets.
