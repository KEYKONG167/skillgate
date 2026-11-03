# skillgate

**A regression gate for skills that agents update themselves.**

[中文说明](README.zh-CN.md)

Agents increasingly rewrite their own skills after a task: a `SKILL.md`, a prompt, a few helper scripts. Most of these updates go live untested. The ones that are tested are usually judged on a handful of examples, and a handful of examples is exactly where a change that is no better *looks* better by luck.

skillgate is a small, dependency-free command-line tool (and Python library) that decides whether an updated skill may replace the current one. It keeps a tamper-evident record of every decision and only grants the skill more autonomy when the evidence supports it.

```
$ skillgate check candidates/better
candidate  847d60e317a9  (champion d150ef7abc67)
practice   champion 31/60, candidate 39/60
sealed     exam taken; 8 left
result     PROMOTED: 847d60e317a9 is the new champion
```

## Why

- **Lucky updates.** Run two equally good versions on 100 cases and one of them will usually score a few points higher. A rule like "keep it if the score went up" keeps nearly half of all changes that do nothing. In the experiments that led to this tool, a prompt update was promoted on a gain of 4 cases. It then scored *worse* on the very cases it had been written from.
- **Teaching to the test.** If whoever edits the skill can see the test results, the skill drifts towards the test and away from the job.
- **Cost.** Running the whole test suite on every edit is expensive, especially when every case is a model call.

## How it works

```
 candidate ──► 1 freeze ──► 2 practice prescreen ──► 3 sealed exam ──► 4 promote? ──► 5 trust level
                 hash          beats the champion      paired with the     clearly better,     earned from the
                 + copy        on cases the agent      champion; stops     and not below the   champion's sealed
                               may see? (free)         early when hopeless original baseline   record
```

1. **Freeze.** The candidate directory is hashed and copied into a store. Every later use re-checks the hash, so a version cannot change after it was judged.
2. **Practice prescreen.** The candidate must beat the current champion on the *practice* cases, which the agent is allowed to see. Most bad edits stop here, at no cost to the sealed exam.
3. **Sealed exam.** The candidate runs on the *sealed* cases, which only the gate sees, in batches and paired case by case with the champion. The exam stops early when the candidate is clearly worse, can no longer win, or is not ahead halfway through. Each exam spends one unit of a fixed budget.
4. **Promote only on evidence.** Only the cases where the two versions disagree count. The candidate is promoted when it is significantly better (exact one-sided sign test, α = 0.05 by default) *and* not below the original baseline. The second condition stops a series of small steps from sliding downhill.
5. **Record and earn trust.** There are two hash-chained ledgers: a practice side, which anyone may read, and a sealed side, which stays with the sealed cases. `check` only ever reveals *promoted or rejected*, the stage, and the remaining budget. A trust level (`human_review` → `spot_check` → `autonomous`) follows from the champion's sealed pass rate, using the lower end of its 95% confidence interval. Add cases from real work to the sealed pool and the trust has to be earned again.

## Quick start (runs offline, no API key)

Requires Python 3.11+.

```bash
git clone https://github.com/KEYKONG167/skillgate
cd skillgate
pip install .
cd examples/email-triage
```

The example "skill" is a rules file that routes support emails to billing, bug, account or other. There are three candidate edits: one really is better, one is worse, and one is a sidegrade that fixes some emails and breaks others.

```
$ skillgate baseline skill
baseline   d150ef7abc67
practice   31/60 passed
sealed     graded on 240 cases (numbers in `skillgate report`)

$ skillgate check candidates/worse
practice   champion 31/60, candidate 17/60
result     REJECTED at practice; the sealed exam was not used (10 left)

$ skillgate check candidates/sidegrade      # one case better on practice, by luck
practice   champion 31/60, candidate 32/60
sealed     exam taken; 9 left
result     REJECTED: d150ef7abc67 stays the champion

$ skillgate check candidates/better
practice   champion 31/60, candidate 39/60
sealed     exam taken; 8 left
result     PROMOTED: 847d60e317a9 is the new champion

$ skillgate report                          # the human's view, with sealed numbers
sealed       175/240 passed (72.9%; at least 67.0% with 95% confidence)
trust level  human_review  (spot_check: >= 90% on 50+ cases, autonomous: >= 98% on 200+ cases)
exams        candidate     champion      ran       wins  losses  p        outcome
             2596d708401b  d150ef7abc67   120/240     3       8  0.97     rejected (not_ahead)
             847d60e317a9  d150ef7abc67   240/240    42       0  2.3e-13  promoted
```

The sidegrade got through the practice prescreen on a lucky one-case lead. The sealed exam stopped it halfway, so it cost half an exam. The better version was promoted, but the skill still stays at `human_review`: 73% is not good enough to hand over.

## Use it with your own skill

1. `skillgate init` writes a commented `skillgate.toml`.
2. Write a **run command** that runs one skill version on one case and prints a result line (see below).
3. Put cases in two pools. **Practice** cases are ones the agent may see and learn from. **Sealed** cases are for the gate only. Each pool is a directory with one sub-directory per case, or a `.jsonl` file with one JSON object per line. Keep the sealed pool where the agent that edits the skill cannot read it.
4. `skillgate baseline path/to/skill` grades the starting version once.
5. In your agent's loop, let the agent edit a *copy* of the skill, then:

```bash
skillgate check work/skill-candidate && skillgate export deploy/skill-next
```

`check` exits with 0 when the candidate was promoted and 1 when it was not, so it drops into scripts and CI.

### The run command

```toml
run = "{python} eval/run_case.py --skill {skill} --case {case}"
```

| placeholder | becomes |
|---|---|
| `{skill}` | path of the frozen skill version under test |
| `{case}` | path of the case: its directory, or a temporary `case.json` holding one JSONL line |
| `{case_id}` | the case id |
| `{python}` | the Python interpreter running skillgate |

The command runs from the directory that holds `skillgate.toml`. Its **last line of output that is a JSON object with a boolean `"pass"`** is the result, for example `{"pass": true, "detail": "sent to billing"}`. A crash, a timeout or a missing result line counts as a fail and is not cached, so a flaky API gets another try on the next run. Results that did come back are cached per version, case content and command, so nothing runs twice.

The run command is the trusted part: it knows the expected answer. Hand the skill only the input, never the expected output. For a skill used by an LLM, a run command typically looks like this:

```python
# eval/run_case.py: a sketch for an LLM skill
skill = Path(args.skill).joinpath("SKILL.md").read_text()
case = json.loads(Path(args.case).read_text())          # {"input": ..., "expected": ...}
answer = call_your_model(system=skill, user=case["input"])
print(json.dumps({"pass": grade(answer, case["expected"])}))
```

### Configuration

| key | default | meaning |
|---|---|---|
| `run` | (required) | command string or list of arguments |
| `timeout` | `300` | seconds per case |
| `jobs` | `4` | cases run in parallel |
| `state` | `.skillgate` | practice-side state: versions, cache, ledger |
| `[practice] cases` | (none) | practice pool; omit it to skip the prescreen |
| `[sealed] cases` | (required) | sealed pool |
| `[sealed] state` | `.skillgate-sealed` next to the cases | sealed-side cache and ledger |
| `[sealed] budget` | `20` | how many candidates may take the sealed exam in total |
| `[rule] alpha` | `0.05` | how sure the gate must be that a candidate is better |
| `[rule] prescreen` | `"better"` | `"better"`, `"not_worse"` or `"off"` |
| `[rule] stop_if_worse` | `true` | stop the exam once the candidate is clearly worse |
| `[rule] futility_after` | `0.5` | after this share of the exam, stop unless the candidate is ahead |
| `[rule] batch` | `20` | how often (in cases) the exam checks whether it can stop |
| `[[levels]]` | spot_check 90%/50, autonomous 98%/200 | trust levels: `name`, `min_pass_rate`, `min_cases` |

### Commands

| command | who it is for | what it does |
|---|---|---|
| `skillgate init [dir]` | you | write a commented config |
| `skillgate baseline <skill>` | you | freeze and grade the starting version, once |
| `skillgate check <candidate> [--json]` | the agent / CI | run the gate; exit 0 if promoted |
| `skillgate status [--json]` | the agent | champion, decisions, budget, trust level; no sealed numbers |
| `skillgate report [--json]` | you | sealed numbers behind every decision; grades the champion on new sealed cases |
| `skillgate export <dir>` | you / CI | copy the champion out for deployment |
| `skillgate verify` | you | check both ledgers and every stored version for tampering |

## How many cases do I need?

Only cases where the two versions disagree carry evidence. With α = 0.05, a candidate needs at least:

| losses | 0 | 1 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|---|
| wins needed | 5 | 7 | 9 | 13 | 20 | 33 |

Suppose a real improvement changes the outcome on 5% of cases and never breaks anything. Then 100 sealed cases give about 5 wins, which is just enough. An improvement that changes 2% of cases needs about 250 cases. **Small exams can only confirm big improvements.** That is by design: if your sealed pool is small, skillgate will tell you that it cannot see a difference rather than promote noise. Rewording a prompt tends to produce small effects. Adding a tool that checks the work, such as a script that recomputes an answer, tends to produce big ones.

## Python API

```python
from skillgate import Gate

gate = Gate.load("skillgate.toml")
decision = gate.check("work/skill-candidate")
if decision.promoted:
    gate.export("deploy/skill-next")
print(gate.status()["trust_level"])
```

## What skillgate does not do

- **It is not a sandbox.** The run command executes the skill. If the skill contains code an agent wrote, run the command inside a container.
- **It cannot hide files from an agent that can read them.** Keep the sealed pool and its state on another machine, or under another user, or anywhere the agent's tools cannot reach.
- **It does not write skills or cases.** Pair it with whatever updates your skills.
- **Every exam is a chance for a lucky pass.** With α = 0.05 and a budget of 20, a stream of useless candidates could slip one through. Keep the budget modest, and add fresh sealed cases from real work over time; `skillgate report` re-grades the champion on them.

## Status

0.1.0, early. The command-line interface and the file formats may still change. Issues and pull requests are welcome.

## License

[MIT](LICENSE)
