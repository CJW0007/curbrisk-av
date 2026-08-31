# Waymo PUDO 数据管道：问题、修复与分析说明

本文件记录从 Jonathan 原始仓库出发所做的数据核查、代码修复、统计分析和
风险解释。修改在独立分支 `fix/data-pipeline-validation` 上完成，便于逐项审阅。

## 1. 原始五个问题

### 1.1 千位逗号导致 exposure 解析失败

CPUC 的 trips/VMT 使用类似 `1,818,206`、`11,233,601.16` 的格式。原代码
直接转换数字，逗号使结果变成 null。

处理：

- 转换前移除千位逗号；
- 严格验证 year、month、trips、P1/P2/P3 VMT 和 total VMT；
- 关键 exposure 无法解析时立即终止，不生成风险率。

真实 2025 Q1 验证结果：

- trips：`1,818,206`；
- VMT：`11,233,601.16`。

### 1.2 2024 aggregate 与 2025+ row-level schema 不同

2024 文件是一行 period totals，2025+ 文件是一行一个 published event flag。
现在分别解析，再映射到统一 canonical columns，并保留 `record_grain`：

- `period_aggregate`；
- `row_level`。

全 9 个真实窗口可做描述，但主要趋势模型只使用 schema 一致的 2025+ 六个
窗口。

### 1.3 2024 ZIP 含其他公司

所有 complaint、monthly 和 location 路径都在汇总前：

- 排除 Drivered 目录；
- 按 Waymo TCPID 过滤；
- 排除 Cruise 和未知 TCPID；
- 兼容 CPUC 某些 Waymo overflow 分片中的已知 TCPID 数字换位。

### 1.4 空风险率仍打印 `[done]`

CLI 现在检查：

- 九个目标 reporting windows；
- 每期预期月份覆盖；
- 正的 trips/VMT；
- 可解析的关键数字；
- 非空的主计数和风险率。

任一检查失败只打印 `[error]` 并返回失败；只有 validation 全部通过才打印：

```text
[done] validation passed; wrote 4 parquet files ...
```

### 1.5 Notebook 保存了错误，模型和风险矩阵未完成

Notebook 已重构为以下顺序：

```text
data grain → hazard → consequence → features/exposure → distribution
→ likelihood model → sensitivity → scenario risk matrix → limitations
```

源 Notebook 清除 execution outputs，已在真实汇总数据上从干净 kernel 完整
执行 20/20 个代码单元格，零错误。

## 2. 深入核查发现的新问题

### 2.1 2380 万空模板不是 samples

官方 2025+ ZIP 中有 `23,825,756` 条逐字节重复的 all-N/redacted 模板行。
风险模型真正的样本是 reporting windows：

| 数据层 | n | 合理用途 |
|---|---:|---|
| Month-Level | 25 个月 | exposure 和运营构成描述 |
| CPUC windows | 9 | 全窗口透明描述 |
| 2025+ comparable windows | 6 | 主要趋势模型 |
| 2025+ non-filler source rows | 11,608 | source/event audit |
| pipeline 保留的现代分析行 | 2,821 | complaint/PUDO actor/severity cross-tab |

Loader 现在做 column projection 和 streaming positive-event filtering。一个
263,000,996-byte 纯模板分片实测只保留 0 行。原 ZIP 仍是审计记录，不能对
真实事件使用简单 `drop_duplicates`。

### 2.2 Redacted 不等于 False

flag mapping 现在是：

- `Y → True/1`；
- `N → False/0`；
- `Redacted/NULL/blank → null`。

`PUDOTravelLane` 的公开 location 值全部 redacted，所以结论是“无法估计”，
不是 0。

### 2.3 Collision frequency 与 actor rows 要分工

`Incidents-Location.CollisionsPUDO` 是直接 collision aggregate；incident actor
flags 可用于 actor/severity linkage，但会漏掉 subtype 未公开的事件。

2025+ 对账：

| Period | Location | Actor-row OR | Gap |
|---|---:|---:|---:|
| 2025 Q1 | 34 | 33 | 1 |
| 2025 Q2 | 54 | 54 | 0 |
| 2025 Q3 | 46 | 46 | 0 |
| 2025 Q4 | 50 | 50 | 0 |
| 2026 Q1 | 69 | 69 | 0 |
| 2026 Q2 | 65 | 63 | 2 |

2024 Dec 也有冲突：aggregate 写 0，但 Location 和 PUDO 小时列都支持 8。
因此 collision frequency 在 Location 可用时统一优先 Location，同时保留
incident/aggregate count 和 reconciliation gap。

### 2.4 Severity flags 是 multi-label

例如 Minor 记录可能同时有 Possible=`Y`。不能把五列直接相加。代码按

```text
Fatal > Severe > Minor > Possible > Property > No listed severity flag
```

为每个 PUDO collision 生成一个互斥的最高 listed severity。

2025+ 的 315 条 actor-linked PUDO collision rows：

- No listed severity flag：292；
- Property damage：2；
- Possible injury：9；
- Minor injury：11；
- Severe injury：1；
- Fatality：0。

`No listed severity flag` 不代表“无伤害”，0 fatality 也不代表未来风险为 0。

## 3. Features 与 samples

运营变量几乎都由服务扩张共同驱动：

- month index vs trips：`r=0.9750`；
- month index vs VMT：`r=0.9744`；
- trips vs VMT：`r=0.9987`；
- P1/deadhead share 随时间下降；
- P3/passenger share 随时间上升。

因此模型只使用：

- `time_months`：主要 predictor；
- `log(VMT)`：primary exposure offset；
- `log(trips)`：PUDO opportunity sensitivity offset。

不把 VMT、trips、passengers、PMT 和 time 同时放进六窗口模型；不把 rate 当
作 predictor 预测自己的 count。`TotalVMTZEV` 与 P1+P2+P3 重复，四个 Waymo
driverless WAV 月度字段为零方差，均不进入模型。

## 4. Distribution 与统计结论

完整九窗口 complaint/VMT rate 强右偏，主要来自 2024 level/schema change：

- mean `0.3765 / 100k VMT`；
- median `0.2807`；
- CV `0.6006`；
- skew `2.3388`。

2025+ 六窗口更窄：

- complaint/VMT mean `0.2672`，CV `0.0905`；
- complaint/trips mean `1.7222`，CV `0.0937`；
- collision/VMT CV `0.2420`。

这些是短时间序列，不是 iid draws。Notebook 使用 time dots、exact Poisson
rate intervals 和 ECDF，而不是依赖 histogram/normality test。

主要 Poisson offset 结果：

| Outcome | Offset | Annual change | 95% CI | p |
|---|---|---:|---:|---:|
| PUDO complaint | VMT | +3.7% | −21.0% to +36.2% | 0.792 |
| PUDO complaint | trips | +12.3% | −14.4% to +47.3% | 0.404 |
| PUDO collision | VMT | −28.2% | −50.4% to +4.1% | 0.080 |
| PUDO collision | trips | −22.1% | −45.1% to +10.7% | 0.163 |

解释：complaint rate 没有足够证据判定上升或下降；collision 有下降信号，
但区间仍跨过 0。完整九窗口的下降结果受 schema change 混杂，只作 sensitivity。

## 5. Consequence 必须按场景拆分

2025+ 总 exposure：`18,603,660 trips`、`121,205,767 VMT`。

| Outcome | Count | /100k trips | /million VMT |
|---|---:|---:|---:|
| PUDO complaint | 325 | 1.7470 | 2.6814 |
| Location PUDO collision | 318 | 1.7093 | 2.6236 |
| Collision with positive severity flag | 23 | 0.1236 | 0.1898 |
| Minor-or-worse collision | 12 | 0.0645 | 0.0990 |
| Severe collision | 1 | 0.0054 | 0.0083 |
| Fatality-coded collision | 0 | 0 | 0 |

PUDO complaint rows与 PUDO collision rows 没有交集，因此 complaint 不能作为
physical harm 的替代指标。Risk register 分为：

1. complaint/service signal；
2. possible/minor-injury collision；
3. severe-injury collision。

课件没有数字 likelihood cutoffs。Notebook 中的 cutoffs 明确标为
project-defined，等待教师/小组确认后可统一替换。

## 6. 生成的数据与验证

Pipeline 输出：

| File | Grain |
|---|---|
| `complaints.parquet` | legacy aggregate / modern relevant event |
| `monthly_activity.parquet` | month |
| `collision_locations.parquet` | tract × reporting window |
| `pudo_summary.parquet` | reporting window |

验证：

- 14/14 自动化测试通过（含同一 tract 冲突重报防重复计数）；
- 端到端 CLI 构建通过；
- Notebook 20/20 代码单元格执行通过；
- Python compile、Notebook validation、`git diff --check` 通过。

## 7. 复现

```bash
cd pudo-pipeline
pip install -e .
pudo-build
jupyter lab notebooks/pudo_analysis.ipynb
python -m unittest discover -s tests -v
```

如果团队以后采用正式 likelihood/consequence 阈值，只需修改 Notebook 的
scenario rubric，不需要重新定义底层 numerator、exposure 或 severity hierarchy。

## 8. Jonathan 最新提交 `42a8ab0` 的整合审查

2026-08-30 重新抓取并逐文件比较了 Jonathan 的 `main`。该提交正确识别了
逗号数字、2024/2025 两套 schema、Waymo TCPID 变体、2026 文件名和 exposure
offset 等方向，但不能整包覆盖本分支：

- 它把约 `23,825,756` 条 all-N/redacted 模板重复行称为 rides，并据此计算
  `per-million-rides`，该分母没有统计意义；
- headline NB 模型混合 2024 aggregate 与 2025+ row schema，无法区分时间趋势
  与 schema level shift；
- collision 仍采用 actor flags/legacy aggregate，分别漏掉 2024-12 的 8 次、
  2025 Q1 的 1 次和 2026 Q2 的 2 次 location collisions；
- Notebook 没有读取 severity，却声称没有 severe PUDO collision；真实现代数据
  有 1 条 severe-injury-coded PUDO collision；
- 缺少季度或月份时仍可能写出结果并显示 `[done]`，且没有新增回归测试。

因此采用 semantic merge：手工吸收安全的 `N/A`/`$` 清洗、八块课程展示说明和
协作文档；保留本分支的 stream filtering、fail-fast validation、九个真实窗口、
六个 modern primary windows、location reconciliation 和 consequence pipeline。
英文逐项对照见 [`UPSTREAM_42A8AB0_REVIEW.md`](UPSTREAM_42A8AB0_REVIEW.md)。
