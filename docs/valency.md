# Valency integration

Valency Bond is the literature database used by this project. The [official MCP reference](https://docs.valency.io/reference/endpoints/) lists discovery, paper detail, analytics and export tools. The [Hub documentation](https://hub.valency.io/docs/mcp) distinguishes reading through Bond from publishing through Hub. The connected tool set does not offer arbitrary CRUD tables for experiments, policies or worker queues; those records live in local SQLite.

## Already connected desktop app

The initial build called the connected Valency `list_sources`, `search_by_title` and `semantic_search_papers` tools. It imported ten relevant metadata records and preserved source, paper/version ID, title, permalink, query, warnings and server version. A later build added two snapshots of eight recent research papers (math.FA/math.SP and hep-th/gr-qc, first submitted August–October 2026) with their `first_submitted` dates, so mining has dated input offline. Generic semantic searches returned ambiguous-match warnings; the snapshots preserve these caveats. No search ranking becomes a proof-validity label.

To add records without a standalone token, export a connected tool's JSON result to a local file, then run:

```bash
python -m danus_rsi literature --import-file valency-result.json
```

The importer accepts a direct object containing `papers`, MCP `structuredContent`, a JSON text MCP content block, or a top-level `snapshots` list. Each paper requires `id`, `source`, `title`, and an HTTPS `url`. Different versions remain distinct. The same exact snapshot can be imported repeatedly without duplicating it. Imports are labeled Valency snapshots on the operator's attestation; the importer does not cryptographically authenticate an arbitrary exported file.

## Standalone application

The [official Direct API guide](https://docs.valency.io/guides/api/) specifies Streamable HTTP at `https://mcp.valency.io/` with a bearer token obtained from Valency settings. The adapter uses the MCP SDK for initialization and protocol negotiation.

```bash
python -m pip install '.[valency]'
# Linux: read without placing the token into shell history.
read -rs -p 'Valency token: ' VALENCY_TOKEN; echo
export VALENCY_TOKEN
python -m danus_rsi literature --query 'mathematical proof verifier calibration' --limit 10
unset VALENCY_TOKEN
```

The token is read from the environment and sent only to the HTTPS Valency host, with redirects disabled. It is not stored in SQLite, reports or role prompts. `.env.example` documents variable names; the application does not automatically read `.env` files. Do not paste a token into an issue, configuration example, Git commit, or model prompt.

An alternative for interactive CLI use is [Valency's Codex CLI OAuth setup](https://docs.valency.io/guides/chatgpt/codex-cli/). That connection belongs to the Codex CLI; this Python adapter uses its own explicit token. The model sessions used for controlled evaluation deliberately ignore MCP/user configuration and do not use an interactive Valency connection.

## Mining benchmark drafts

`mine --since YYYY-MM-DD` reads stored records (optionally after a fresh standalone `--query`) and keeps only papers that:

- carry a `first_submitted` date on or after `--since`. Undated records are excluded, because recency is the only contamination control available from metadata;
- have an arXiv category that maps to a benchmark domain: `math.*` → mathematics; `math-ph`/`math.MP`, `hep-th`, `hep-ph`, `gr-qc`, `quant-ph`, `nucl-th`, `cond-mat.*`, `nlin.*`, `physics.*`, `astro-ph.*` → theoretical physics. A paper can map to both.

Choose `--since` after the model's training cutoff when it is known. A recent date limits, but cannot exclude, contamination: results circulate before arXiv submission. Mining reads metadata and any abstracts in the snapshot, never full texts, so every draft needs a reviewer who reads the paper. See [protocol](protocol.md#benchmark-growth).

## Provenance model

A snapshot records the provider, original query/tool, retrieval time when known, server version when supplied, warnings, and returned paper metadata. A paper identity includes its corpus/source and versioned ID. Full contents are content-addressed, so changed metadata produces a separate artifact. Paper URLs are retained for the human researcher to inspect.

Imported seeds contain metadata only. Live search requests abstracts, and those excerpts may be passed to the curator/researcher. Neither source type establishes that a full paper was read. Curators must identify missing evidence, and candidate proofs must be self-contained or explicitly state unresolved dependencies. Citation presence is not correctness, and a literature search does not certify novelty.

No write-to-Hub, feedback submission, or automatic publication operation is implemented or invoked.
