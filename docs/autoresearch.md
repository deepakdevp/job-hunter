# Autoresearch

The deep autoresearch engine is inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) pattern. It performs iterative, evidence-based research on high-value jobs to improve scoring confidence.

## What it does

For each job above a score threshold:

1. **Company Research** -- culture, engineering blog, Glassdoor reviews, visa history
2. **Visa Verification** -- checks career pages, H1B data, immigration forums
3. **Evidence-Based Re-Scoring** -- adjusts the score using gathered evidence
4. **Resume Optimization** -- flags resume gaps and suggests improvements

Results are logged to an append-only TSV file with status (keep/discard/skip), confidence level, and citations.

## Commands

```bash
# Single pass: research all jobs with score >= 5
hunt research run --min-score 5 --max-jobs 50

# Loop mode: runs until Ctrl+C, re-researches low-confidence results
hunt research loop --min-score 5 --max-jobs 50
```

## The program.md Steering File

The `config/deep_research_program.md` file is the human-agent interface. Edit it to steer research priorities without touching code.

The agent reads this file at the start of each loop iteration. It controls:

- **Research priorities** -- what matters most (e.g., visa sponsorship 50%, role fit 30%, skills 20%)
- **Keep/discard thresholds** -- minimum confidence and citation count to persist a score change
- **Time budget** -- seconds per job before moving on (default: 120s)
- **Max rounds** -- company research rounds and visa verification rounds
- **Loop behavior** -- what to re-research, what to skip

Example excerpt:

```markdown
## Research Priorities (ordered)

1. **Visa sponsorship** (50% weight) — #1 blocker. Look for:
   - Company career page mentioning "visa sponsorship"
   - H1B data showing the company sponsors visas
   - Immigration forums confirming sponsorship

2. **Role fit** (30% weight) — Does the role match skills?

3. **Skills match** (20% weight) — Specific technology overlap
```

## Single Pass vs Loop Mode

### Single pass (`hunt research run`)

- Processes each qualifying job once
- Logs results and exits
- Good for a one-time deep dive

### Loop mode (`hunt research loop`)

- Runs continuously until Ctrl+C
- After each iteration, re-researches jobs with LOW confidence
- Skips jobs already at HIGH confidence
- Each iteration reads the latest `program.md` (you can edit it while the loop runs)

## Keep/Discard Logic

Not every research result changes the score. The engine uses confidence thresholds:

| Confidence | Meaning | Action |
|-----------|---------|--------|
| HIGH | 2+ independent sources agree | Keep the score change |
| MEDIUM | 1 source with strong signal | Keep the score change |
| LOW | Weak or no evidence | Discard (do not update score) |

In loop mode, LOW-confidence results are queued for re-research on the next iteration.

## Caching

- **Company cache** -- same company across multiple jobs = one research session
- **Visa cache** -- visa status cached per company
- Caches persist across loop iterations but reset between separate `hunt research` invocations

## Output

Results are appended to `config/deep_research_results.tsv`:

```
timestamp	job_url	company	status	old_score	new_score	confidence	citations	reasoning
```

Status values: `keep`, `discard`, `skip` (below threshold), `crash` (error during research).

## Module Structure

```
autoresearch/
  deep_research.py     Main engine (run_deep_research, run_deep_research_loop)
  source_research.py   Web search and source discovery
  web_tools.py         HTTP fetching utilities
  resume_audit.py      Resume gap analysis
  score_audit.py       Score explanation with citations
  data_validation.py   Research output validation
```
