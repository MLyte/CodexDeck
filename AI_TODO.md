# AI_TODO

## ChatGPT Token Usage Checks

- [ ] TOK01 Run a short ChatGPT prompt and record the approximate input/output token budget before launching Codex.
- [ ] TOK02 Ask ChatGPT to summarize a 500-word note in 5 bullets and compare the estimated token usage with the visible response length.
- [ ] TOK03 Test whether a long prompt with redundant context can be reduced without changing the expected answer.
- [ ] TOK04 Compare fast mode and normal model mode on the same prompt, then note the response quality and latency tradeoff.
- [ ] TOK05 Ask ChatGPT to produce a compact handoff summary from a noisy conversation and verify it keeps the critical constraints.
- [ ] TOK06 Run a prompt that includes a fake secret value and verify the resulting logs or summaries do not expose sensitive-looking content.
- [ ] TOK07 Ask ChatGPT to explain why a prompt exceeded context limits and propose a smaller prompt structure.
- [ ] TOK08 Test a multilingual prompt, then verify the model keeps the final answer in the requested language.
- [ ] TOK09 Ask ChatGPT to transform a TODO list into execution batches and verify that dependencies are preserved.
- [ ] TOK10 Review `CODEX_RUNS.md` after several runs and verify each launched task has a readable Markdown summary.
