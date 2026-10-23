# Foundation and research provenance

This project extends the prior local **Danus Math Panel 1.0.0**. It retains the twelve authored graduate/research-style mathematics problems as development data and adapts the prior isolated CLI transport, native-verifier boundary, rubric and validation functions. Original source hashes are preserved in `danus_rsi/data/foundation-provenance.json`; no private run state or authentication material was copied.

The external runtime is [frenzymath/Danus](https://github.com/frenzymath/Danus), examined at commit `6d92e8d415933ca2ef52fd1a4da73fdfcd418f1c`, licensed Apache-2.0. This repository calls Danus's shared CLI launcher and native verifier API. It does not bundle the upstream runtime or claim to be an official upstream release.

The new physics prompts, references and deliberately invalid candidates were authored for this project around standard theoretical arguments. They emphasize assumptions, derivations and boundaries. They are public development examples, not expert-certified truth, a private held-out evaluation, an empirical assessment of frontier-model ability, or newly discovered theorems. Subject-matter review remains necessary before using them for research conclusions.

## Valency literature seeds

Ten metadata records were retrieved from the connected Valency database on 2026-10-22. Their source/version IDs, URLs, query provenance and search warnings are retained in `danus_rsi/data/valency-seed.json`. They provide a starting bibliography; their full texts were not reviewed in this build.

- [Danus: Orchestrating Mathematical Reasoning Agents with Fact-Graph Memory](https://arxiv.org/abs/2607.06447)
- [Hard2Verify: A Step-Level Verification Benchmark for Open-Ended Frontier Math](https://arxiv.org/abs/2510.13744)
- [AdvancedMathBench: A Benchmark Suite for Advanced Mathematical Proof Generation and Verification](https://arxiv.org/abs/2607.11849)
- [PRIME: A Process-Outcome Alignment Benchmark for Verifiable Reasoning in Mathematics and Engineering](https://arxiv.org/abs/2602.11570)
- [VerifyBench: A Systematic Benchmark for Evaluating Reasoning Verifiers Across Domains](https://arxiv.org/abs/2507.09884)
- [FormalProofBench: Can Models Write Graduate Level Math Proofs That Are Formally Verified?](https://arxiv.org/abs/2603.26996)
- [Naive Dimensional Analysis and Irrelevant Operators](https://arxiv.org/abs/1105.3178)
- [Generalized Dimensional Analysis](https://arxiv.org/abs/hep-ph/9207278)
- [Analysis of General Power Counting Rules in Effective Field Theory](https://arxiv.org/abs/1601.07551)
- [Effective Field Theories and the Role of Consistency in Theory Choice](https://arxiv.org/abs/1211.0634)

No accuracy, scientific claim or promotion threshold in this implementation is asserted to have been validated by these papers. A record returned by semantic search can be relevant without being authoritative for a particular claim.

Official integration references: [Valency Direct API](https://docs.valency.io/guides/api/), [Valency endpoints](https://docs.valency.io/reference/endpoints/), [Valency/ChatGPT connection boundaries](https://docs.valency.io/guides/chatgpt/), and [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode).
