# Evaluation and recursive improvement protocol

## Scope and trust boundary

Let a policy $\pi_t$ consist of a solver strategy, verifier guidance, and a curriculum focus. Two improvement arms revise it, never in the same experiment:

| Arm | May change | Held fixed | Measured on |
|---|---|---|---|
| Verifier | verifier guidance, name, rationale | solver strategy, curriculum | labeled fixed candidates (balanced accuracy) |
| Solver | solver strategy, name, rationale | verifier guidance, curriculum | generated solutions judged by the strict panel (strict-accept count) |

Each arm holds the other side fixed so that a score change has one cause. In particular, a solver strategy can never raise its own score by loosening the check it is judged by; code rejects any proposal that touches a frozen field. Curriculum focus is not optimized in this release. New benchmark problems are separate unreviewed drafts.

The sequence is

$$
\pi_t \longrightarrow \widetilde\pi_{t+1}
\longrightarrow \operatorname{Eval}_{D_{\rm dev}}(\pi_t,\widetilde\pi_{t+1})
\longrightarrow \pi_{t+1}^{\rm experimental}.
$$

Only development examples, their labels and the corresponding feedback enter the optimizer context. A rejected proposal leaves the development branch unchanged. The next cycle evaluates and optimizes the selected branch again. The active production policy is separate and is changed only after a qualifying private audit. This is bounded strategy improvement, not a claim of unbounded intelligence growth.

Trusted components: operator/reviewer attestations, Python evaluator code, the SQLite owner, and the private audit custodian. Untrusted components: model text, generated task references, paper search results, and proposed strategies. Models have no database or filesystem tools. They cannot edit gates, budgets, labels or code through the structured proposal interface.

## Frozen panel rule

The panel comprises correctness, adversarial, and completeness judges. Each sees the original problem, authored reference/rubric, and candidate; it does not see candidate identity, other votes, calibration labels, or the native result. Independent calls share a base model, so independence of errors is **not** assumed.

Each judge reports a verdict, four scores in $\{0,1,2,3,4\}$, explicit errors/gaps, rationale and reference concerns. The descriptive score is

$$
S=\frac{1}{4}\sum_d w_d\operatorname{median}_{j=1}^{3}s_{jd},
\qquad w=(50,25,20,5).
$$

This score cannot override the logical acceptance gate. An acceptance needs all three judges to report correctness score 4, completeness and rigor at least 3, no errors/gaps/reference concerns, and a consistent native `correct` verdict. A rejection needs three explicit negative judgments with concrete defects. Dissent, uncertain verdicts, low positive scores, unresolved references, or a positive panel conflicting with a negative native check lead to abstention. Invalid schemas, contradictory native results and failed calls are infrastructure errors.

The native service verifies a submitted claim and proof; panel judges additionally check that these answer the original question. A claim proving something unrelated is insufficient. Native checking is informal model verification, not a proof kernel.

## Metrics and promotion

For labeled valid and invalid candidates, define

$$
\operatorname{BA}=\frac12\left(\frac{\mathrm{accepted\ valid}}{n_{\rm valid}}
+\frac{\mathrm{rejected\ invalid}}{n_{\rm invalid}}\right),\qquad
\operatorname{FAR}=\frac{\mathrm{accepted\ invalid}}{n_{\rm invalid}}.
$$

Coverage is the proportion with a determinate accept/reject result. Abstentions and infrastructure errors do not count as correct rejections. Metrics use all selected cases, so failed cases cannot silently disappear from denominators.

An audit uses identical fixed candidate proofs for the baseline and proposal; policy order alternates by case. The gate requires:

1. Complete coverage for both policies.
2. $\Delta\operatorname{BA}\ge 0.05$.
3. No increase in false acceptances, globally or within either domain.
4. No balanced-accuracy regression within mathematics or theoretical physics.
5. Complete determinate evaluations on frozen development regression cases, with no previously correct classification becoming incorrect.
6. Unchanged active baseline, evaluator code hash, and regression-suite hash when activating the policy.

The fixed numerical threshold is a conservative software rule, **not** a significance test. Small batches, correlated judges, author-label error, dataset contamination, and adaptivity can still undermine external validity. Report case counts and disagreements, not just an aggregate score. Repeated stochastic trials and larger expert-reviewed batches are needed before interpreting a result as a research capability gain; this release runs one sample per role per case.

## Private audit input

An independently maintained file outside version control has this structure. The snippet shows one case only; a real audit must contain at least 20 cases across at least ten families, with at least five valid and five invalid candidates in each domain.

```json
{
  "id": "custodian-batch-001",
  "split": "audit",
  "review_status": "independently-reviewed",
  "reviewer": "Named reviewer or review team",
  "provenance": "How the problems and labels were independently checked",
  "cases": [{
    "id": "unique-case-id",
    "label": "valid",
    "task": {
      "id": "problem-id",
      "family_id": "stable-underlying-problem-family",
      "title": "Descriptive title",
      "domain": "mathematics",
      "prompt": "Precisely stated question with hypotheses",
      "reference": "Independently checked argument",
      "rubric": ["Checkable condition"]
    },
    "solution": {"answer": "Candidate answer", "claim": "Exact claim", "proof": "Candidate proof"}
  }]
}
```

The reviewer field is an attestation, not a cryptographic identity verification. Automated tests cannot certify an expert's work. Do not turn a model's own preference into an audit label.

Audits reject declared family overlap and whitespace/case-normalized statement overlap with public development, imported curricula, generated drafts, and research exposure. The whole batch and its statement/family fingerprints are reserved before the first call. Re-labeling a previously consumed problem or renaming the batch does not make it fresh. A failed or interrupted audit cannot be resumed or reused. Similar paraphrases with misleading family IDs still require human detection.

Audit labels/results are stored only in ignored local state and are never supplied to the optimizer. The HTML/Markdown report omits case content; full JSON remains private. The repository contains no real private audit set.

## Solver arm

A solver development cycle selects development problems, generates one candidate per problem under the current branch, judges each with the same panel and native check as the benchmark, and asks the solver optimizer for revised solver guidance. The optimizer sees problem statements, the decisions, the reviewers' stated defects and the solve counts. It never sees references. A proposal is rejected without evaluation, and the branch is unchanged, if it changes a frozen field, leaves the solver guidance unchanged, or quotes a development prompt or reference sentence of 60 or more characters verbatim. Otherwise the revised strategy solves the same problems and the frozen solver rule decides the branch.

Each policy makes $k$ independent attempts at each of $n$ problems (`--samples k`, $1\le k\le 5$, default 1). With decisions $d_{ij}^{b}, d_{ij}^{c}$ for problem $i$ and attempt $j$, let $A_b=\#\{(i,j): d_{ij}^b=\text{accept}\}$ and $A_c$ likewise. The solver gate (protocol `danus-rsi-solver-v2`) requires:

1. Identical problem order, domains and attempt counts in both arms.
2. No infrastructure errors in either arm.
3. $A_c - A_b \ge \max(1, \lceil 0.10\,nk\rceil)$.
4. No decrease of strict accepts within mathematics or theoretical physics.

With $k=1$ this is exactly the earlier single-sample rule, and the call keys are unchanged. Problems where the candidate has fewer accepted attempts than the baseline are reported as `lost_solves`. A strict accept still needs the native check and all three judges; abstention never counts as a solve.

Every result also reports a 95% Wilson interval for the strict-accept rate, and verifier metrics report one for each label class. The intervals are descriptive and never enter a gate. They show the problem plainly: with one attempt at each of four problems and no accepts, the interval for the solve rate is $[0, 0.49]$. More samples narrow it at a linear cost in calls. Development selection only moves the experimental branch, and activation needs a fresh solver audit, which also accepts `--samples`.

Reviewers see the reference, so a defect they state can quote it. Before feedback reaches the solver optimizer, any defect that repeats eight consecutive words of the problem's reference is replaced by a withheld marker, and the count is recorded. Paraphrase passes this filter, so isolation from references is a strong default, not a guarantee. Verbatim-copy detection on proposed strategies catches memorized text, not paraphrased answers; the private audit is the real check of transfer.

## Solver audit input

A solver audit is a fresh, independently reviewed problem set without candidate proofs. The candidate must equal the active policy except for solver guidance, name and rationale. Baseline and candidate each attempt every problem, in alternating order, under the active verifier guidance; the solver gate above decides eligibility. Budget ten calls per problem.

```json
{
  "id": "custodian-solver-batch-001",
  "split": "solver-audit",
  "review_status": "independently-reviewed",
  "reviewer": "Named reviewer or review team",
  "provenance": "How the problems and references were independently checked",
  "tasks": [{"id": "unique-problem-id", "family_id": "stable-family", "title": "Descriptive title",
             "domain": "theoretical-physics", "prompt": "Precisely stated question", "reference": "Independently checked argument",
             "rubric": ["Checkable condition"]}]
}
```

`audit-template --arm solver|verifier --out PATH` writes a worksheet that fails validation until a reviewer completes and signs it, and refuses paths inside the repository other than its ignored `.state/`. `audit-check PATH` validates a batch, checks it against current exposure and the consumed-problem registry, and reports counts and `"fresh"` without reserving anything or printing case content.

A batch needs at least 12 problems, at least 8 families, and at least five problems in each domain. Overlap rules are the same as for verifier audits. Both audit kinds share one consumed-problem registry: a problem or family consumed by either arm can never be fresh for the other. `audit --file` selects the arm from the file's `split`; `promote` and `rollback` work for both.

## Benchmark growth

Optimizer proposals are stored as `benchmark_draft` artifacts with `review_status=unreviewed`. For an independently reviewed set, prepare a development-suite JSON with `split=development`, `review_status=independently-reviewed`, `reviewer`, and `tasks` in the public task format. Then:

```bash
python -m danus_rsi import-curriculum reviewed-development.json
```

Task IDs are immutable: revised content needs a new task ID and the same underlying family ID. Imports immediately become development exposure and can never be relabeled as a fresh audit. This intentionally keeps benchmark expansion dependent on independent label quality.

The Valency miner is a second draft source. `mine --since DATE` restricts input to math/physics records first submitted on or after `DATE`, then asks the miner for at most three drafts per batch of papers. Code rejects a draft that cites a record outside its batch, whose domain does not match the cited papers' arXiv categories, or whose family or normalized statement repeats a problem already exposed (development data, research tasks, earlier drafts, or another draft in the same run). Accepted drafts carry `origin=valency-miner`, the cited paper identities and permalinks, and reviewer notes. They are exposure from the moment they exist, so they can enter development data but never an audit. To review them:

```bash
python -m danus_rsi drafts --origin valency-miner --export review.json
# A reviewer checks each statement against the full paper, edits or deletes tasks,
# adds calibration candidates if wanted, then sets review_status and reviewer.
python -m danus_rsi import-curriculum review.json
```

The exported file has `review_status=pending-review`, which `import-curriculum` refuses until a reviewer signs it.
