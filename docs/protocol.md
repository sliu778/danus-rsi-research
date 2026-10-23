# Evaluation and recursive improvement protocol

## Scope and trust boundary

Let a policy $\pi_t$ consist of a solver strategy, verifier guidance, and a curriculum focus. The optimizer in this release may change only verifier guidance, its name, and its explanatory rationale. Solver strategy and curriculum focus are held fixed because the experiment measures verification of fixed candidates, not generated solution quality. New benchmark problems are separate unreviewed drafts.

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

## Benchmark growth

Optimizer proposals are stored as `benchmark_draft` artifacts with `review_status=unreviewed`. For an independently reviewed set, prepare a development-suite JSON with `split=development`, `review_status=independently-reviewed`, `reviewer`, and `tasks` in the public task format. Then:

```bash
python -m danus_rsi import-curriculum reviewed-development.json
```

Task IDs are immutable: revised content needs a new task ID and the same underlying family ID. Imports immediately become development exposure and can never be relabeled as a fresh audit. This intentionally keeps benchmark expansion dependent on independent label quality.
