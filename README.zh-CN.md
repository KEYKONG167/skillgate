# skillgate

**给「AI 自己改自己的 skill」装一道验收闸门。**

[English](README.md)

现在越来越多的 agent 会在做完任务后，自己修改自己的 skill：一份 `SKILL.md`、一段提示词、几个辅助脚本。这些改动大多没经过检验就直接上线了。就算检验，通常也只拿几个例子试一试，而例子少的时候，一个其实没变好的改动，很容易**看起来**变好了，只是运气。

skillgate 是一个很小、不依赖任何第三方库的命令行工具（也能当 Python 库用）。它负责判断改过的 skill 能不能替换现在这一版，把每一次判断都记进一本改不了的账，并且只在证据够了的时候，才给这个 skill 更多自主权。

```
$ skillgate check candidates/better
candidate  847d60e317a9  (champion d150ef7abc67)
practice   champion 31/60, candidate 39/60
sealed     exam taken; 8 left
result     PROMOTED: 847d60e317a9 is the new champion
```

## 为什么需要它

- **运气好的改动。** 两个水平一样的版本，在 100 道题上比，总有一个会多对几道。如果规则是「分数涨了就换」，那么什么用都没有的改动里，差不多一半会被换上去。做这个工具之前的实验里，就有一次提示词改动靠多对 4 道题被换上了，结果它在自己照着改的那批练习题上反而更差。
- **对着考卷刷题。** 如果改 skill 的一方能看到考试结果，skill 就会慢慢朝着考卷去改，离真正的活越来越远。
- **成本。** 每改一次就把整套测试跑一遍，很贵，尤其是每道题都要调用一次模型的时候。

## 怎么工作

打个比方：skill 是一位改卷老师，改 skill 的 agent 是教练，skillgate 是校长。

1. **冻结。** 新版本按文件内容算出一个指纹，复制一份存起来。以后每次用都重新核对指纹，判过的版本就没法再偷偷改。
2. **练习题先筛。** 新版本得先在**练习题**上比现在的版本做得好。练习题是教练本来就能看到的，所以不花考卷。大部分不好的改动在这一步就被筛掉了。
3. **锁着的考卷，边考边看。** 新版本和现任版本在同一批**封存题**上逐题对比，一批一批地考。如果明显更差、已经不可能赢、或者考到一半还没领先，就提前停下。每考一次，消耗一次固定的考试额度。
4. **证据够了才换。** 只看两个版本判得不一样的那些题。新版本必须**明显**更好（单侧精确符号检验，默认 α = 0.05），而且**不能比最初的版本差**。第二条防止一点一点往下滑。
5. **记账，凭证据放权。** 账本有两本，都是哈希链，改动任何一条都会被发现。一本是练习这一侧，谁都能看；另一本是封存这一侧，跟封存题放在一起。`check` 只会告诉调用方「换上了」还是「没换上」、卡在哪一关、还剩几次考试额度。信任等级分 `human_review`（人全审）、`spot_check`（人抽查）、`autonomous`（自主），按现任版本在封存题上的通过率来定，用的是 95% 置信区间的下限。从实际工作里补充新的封存题以后，信任要重新挣。

## 快速体验（不联网，不需要 API 密钥）

需要 Python 3.11 或更高版本。

```bash
git clone https://github.com/KEYKONG167/skillgate
cd skillgate
pip install .
cd examples/email-triage
```

例子里的「skill」是一个规则文件，负责把客服邮件分到账单、故障、账号、其他四类。准备了三个改动：一个真变好了，一个改坏了，还有一个「拆东墙补西墙」，修好了一部分邮件，又弄错了另一部分。

```
$ skillgate baseline skill
baseline   d150ef7abc67
practice   31/60 passed
sealed     graded on 240 cases (numbers in `skillgate report`)

$ skillgate check candidates/worse
practice   champion 31/60, candidate 17/60
result     REJECTED at practice; the sealed exam was not used (10 left)

$ skillgate check candidates/sidegrade      # 运气好，在练习题上多对了 1 道
practice   champion 31/60, candidate 32/60
sealed     exam taken; 9 left
result     REJECTED: d150ef7abc67 stays the champion

$ skillgate check candidates/better
practice   champion 31/60, candidate 39/60
sealed     exam taken; 8 left
result     PROMOTED: 847d60e317a9 is the new champion

$ skillgate report                          # 给人看的，带封存题的数字
sealed       175/240 passed (72.9%; at least 67.0% with 95% confidence)
trust level  human_review  (spot_check: >= 90% on 50+ cases, autonomous: >= 98% on 200+ cases)
exams        candidate     champion      ran       wins  losses  p        outcome
             2596d708401b  d150ef7abc67   120/240     3       8  0.97     rejected (not_ahead)
             847d60e317a9  d150ef7abc67   240/240    42       0  2.3e-13  promoted
```

「拆东墙补西墙」那个版本靠运气在练习题上领先 1 道，混过了第一关，但封存考试考到一半就把它停了，只花了半场考试。真变好的版本被换上了，但信任等级还是 `human_review`，因为 73% 的通过率还不够把活交给它。

## 用在你自己的 skill 上

1. `skillgate init`：生成一份带注释的 `skillgate.toml`。
2. 写一条**运行命令**：用某个版本的 skill 做一道题，打印一行结果（见下文）。
3. 把题目分成两堆。**练习题**是 agent 可以看、可以拿来学的；**封存题**只给闸门用。每一堆可以是一个文件夹（每道题一个子文件夹），也可以是一个 `.jsonl` 文件（每行一个 JSON 对象）。封存题要放在改 skill 的 agent 读不到的地方。
4. `skillgate baseline path/to/skill`：给起始版本打一次底。
5. 在 agent 的循环里，让 agent 改 skill 的**副本**，改完：

```bash
skillgate check work/skill-candidate && skillgate export deploy/skill-next
```

`check` 换上了就返回 0，没换上就返回 1，可以直接放进脚本或 CI。

### 运行命令

```toml
run = "{python} eval/run_case.py --skill {skill} --case {case}"
```

| 占位符 | 替换成 |
|---|---|
| `{skill}` | 被测的那个冻结版本的路径 |
| `{case}` | 这道题的路径：题目文件夹，或者装着一行 JSONL 的临时 `case.json` |
| `{case_id}` | 题目编号 |
| `{python}` | 运行 skillgate 的那个 Python |

命令在 `skillgate.toml` 所在的目录里运行。它输出的**最后一行带布尔值 `"pass"` 的 JSON** 就是结果，比如 `{"pass": true, "detail": "sent to billing"}`。崩溃、超时、或者没有结果行，都算没通过，而且不缓存，下次会重试，避免把接口偶尔抽风记成真失败。正常拿到的结果按「版本 + 题目内容 + 命令」缓存，同一道题不会跑两遍。

运行命令是可信的那一方，它知道标准答案。交给 skill 的只能是题目本身，不能带答案。如果是给大模型用的 skill，运行命令大致是这样：

```python
# eval/run_case.py：给大模型用的 skill，示意
skill = Path(args.skill).joinpath("SKILL.md").read_text()
case = json.loads(Path(args.case).read_text())          # {"input": ..., "expected": ...}
answer = call_your_model(system=skill, user=case["input"])
print(json.dumps({"pass": grade(answer, case["expected"])}))
```

### 配置项

| 配置 | 默认值 | 含义 |
|---|---|---|
| `run` | 必填 | 命令字符串，或参数列表 |
| `timeout` | `300` | 每道题最多跑几秒 |
| `jobs` | `4` | 同时跑几道题 |
| `state` | `.skillgate` | 练习这一侧的数据：版本、缓存、账本 |
| `[practice] cases` | 无 | 练习题；不填就跳过「练习题先筛」 |
| `[sealed] cases` | 必填 | 封存题 |
| `[sealed] state` | 封存题旁边的 `.skillgate-sealed` | 封存这一侧的缓存和账本 |
| `[sealed] budget` | `20` | 总共允许几个新版本参加封存考试 |
| `[rule] alpha` | `0.05` | 要多有把握才算「明显更好」 |
| `[rule] prescreen` | `"better"` | `"better"`（必须更好）、`"not_worse"`（不更差）或 `"off"`（不筛） |
| `[rule] stop_if_worse` | `true` | 明显更差就提前停 |
| `[rule] futility_after` | `0.5` | 考到这个比例还没领先，就停 |
| `[rule] batch` | `20` | 每考多少道检查一次能不能停 |
| `[[levels]]` | spot_check 90%/50 道，autonomous 98%/200 道 | 信任等级：`name`、`min_pass_rate`、`min_cases` |

### 命令

| 命令 | 给谁用 | 做什么 |
|---|---|---|
| `skillgate init [dir]` | 你 | 生成带注释的配置 |
| `skillgate baseline <skill>` | 你 | 冻结起始版本并打底，只做一次 |
| `skillgate check <candidate> [--json]` | agent / CI | 过闸门；换上了返回 0 |
| `skillgate status [--json]` | agent | 现任版本、历次结果、剩余额度、信任等级；不含封存题的数字 |
| `skillgate report [--json]` | 你 | 每次判断背后的封存题数字；会先让现任版本把新补进来的封存题做一遍 |
| `skillgate export <dir>` | 你 / CI | 把现任版本复制出来部署 |
| `skillgate verify` | 你 | 检查两本账和所有存下来的版本有没有被改过 |

## 需要多少道题？

只有两个版本判得不一样的题才算证据。在 α = 0.05 下，新版本至少要赢这么多道：

| 输了几道 | 0 | 1 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|---|
| 至少要赢几道 | 5 | 7 | 9 | 13 | 20 | 33 |

假如一个真实的进步能改变 5% 题目的结果，而且什么都没弄坏，那么 100 道封存题大约能赢 5 道，刚好够。如果只改变 2% 的题，就要 250 道左右。**题少的考卷只能证明大的进步。** 这是故意这么设计的：封存题不够多时，skillgate 会告诉你「看不出区别」，而不是把运气当成进步。改提示词的措辞往往只带来小进步；加一个能检查工作的工具，比如重新算一遍答案的脚本，往往能带来大进步。

## Python 接口

```python
from skillgate import Gate

gate = Gate.load("skillgate.toml")
decision = gate.check("work/skill-candidate")
if decision.promoted:
    gate.export("deploy/skill-next")
print(gate.status()["trust_level"])
```

## skillgate 不做什么

- **它不是沙箱。** 运行命令会真的执行 skill。如果 skill 里有 agent 写的代码，请在容器里跑运行命令。
- **它没法把文件藏起来。** agent 能读到的文件，它就能读到。封存题和封存那一侧的数据，请放在另一台机器、另一个用户名下，或者任何 agent 的工具够不着的地方。
- **它不写 skill，也不出题。** 改 skill 的那一方你自己选，它只负责验收。
- **每考一次，都有一点「运气过关」的可能。** α = 0.05、额度 20 次的话，一连串没用的改动里，可能会有一个靠运气混过去。额度别给太多；从实际工作里不断补充新的封存题，`skillgate report` 会让现任版本把它们重新做一遍。

## 状态

0.1.0，早期版本，命令行和文件格式还可能变。欢迎提 issue 和 pull request。

## 许可证

[MIT](LICENSE)
