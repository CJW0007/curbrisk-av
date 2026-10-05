# DEM evidence and classroom validation

This module keeps the DEM blocking analysis separate from the older CPUC PUDO pipeline. It contains an independent numerical re-check, a small exploratory prediction comparison, and one DEM classroom slide with a separate teacher-workbook PUDO backup.

In the tested 117-report sample, logistic regression and a shallow decision tree did not show convincing prediction improvement over a prevalence baseline. The evidence-sensitive H2 result is more important for the risk matrix: the broad, inferred-obstruction scenario is Very high; explicit obstruction alone is Medium.

## Classroom files

- `classroom/AV_DEM_Main_PUDO_Backup.pptx`: editable two-slide deck. Slide 1 is the one-page DEM main display; slide 2 is a separate PUDO backup.
- `classroom/AV_DEM_Main_PUDO_Backup.pdf`: static view of those two slides.
- `classroom/Class_Talk_and_Methods_ZH_EN.pdf`: simple spoken English, corresponding Chinese, model choices and limits.
- `results/model_brier.png`: probability-error comparison, lower is better.

The 24-case full narrative review packet remains local. `review/review_template.csv` contains source locators and blank review fields, not completed human judgments. Existing labels are withheld. The selection is purposive, not a population validation sample; prior exposure prevents a fully blind claim. No new human agreement score is reported.

## Verified quantities

| Question | Result | Scope |
| --- | --- | --- |
| DEM report rate | 117 / 184 × 30 = 19.08 reports per 30 days | March and June–October 2025; assumed calendar coverage, not trips |
| Long logged events | 34 / 117 = 29.1% | Operational cutoff of at least 60 minutes |
| Share of logged event minutes | 74.3%; 71.6% without the longest report | Event intervals, not medical delay, person-minutes or measured harm |
| H2 inferred Severe scenario | 3 qualifying reports; 30-day probability 0.4106 | Potential consequence at life-threatening scenes, not proven AV injury |
| H2 explicit Major obstruction | 1 qualifying report; probability 0.2027 | Strict evidence alternative; records are not deleted |
| Teacher PUDO comparison | RR 1.0926; exact 95% CI 0.8272–1.4322; p=0.5354 | Latest quarter vs prior three pooled, complaints per trip |

The probability and consequence must describe the same event tier. Counting all six H2 events and attaching the rarer Severe consequence would overstate the matrix placement. DEM calendar-day rates and PUDO trip rates are not combined.

## Exploratory duration comparison

Target: logged duration ≥60 minutes. Inputs: recorded AV count with a missing indicator, start clock time as sine/cosine, and supplied nominal area. Inputs exclude duration, clear time, narratives, hazard labels and impact scores. The supplied area labels are not independently validated geography.

All models use the same five `GroupKFold` splits by calendar date. Preprocessing is fitted inside the training folds. Hyperparameters and the 0.5 cutoff are fixed, with no tuning. These are retrospective recorded fields; AV count is not established as available at event start.

| Model | ROC AUC | Average precision | Brier score ↓ |
| --- | ---: | ---: | ---: |
| Training prevalence baseline | 0.4607 | 0.2743 | 0.2067 |
| L2 logistic regression | 0.3955 | 0.2945 | 0.2349 |
| Shallow tree | 0.4476 | 0.2641 | 0.2545 |

Both fitted models have greater probability error than the baseline. This does not prove the fields have zero predictive value or that all models fail. The additional August–October check is historically examined data, not untouched prospective validation. Fold spread is not a confidence interval. The baseline is constant within each fold; varying training prevalence makes its pooled AUC differ from 0.5.

## Reproduce the checks

Use an existing Python environment with the packages in `requirements.txt`. Results were fitted with Python 3.14.6, NumPy 2.4.6, pandas 3.0.3, SciPy 1.18.0, scikit-learn 1.9.0, openpyxl 3.1.5 and matplotlib 3.11.0. Package versions can change numeric details; compare the saved predictions and metrics.

Acquire the source from [Jonathan’s repository](https://github.com/jonathanwilsonami/av-blocking-analysis) at the exact revision `06fdb2e928ab133f799015ae01323c991669ddcd`, keeping its `data/` layout. Workbooks are not redistributed here. The runner checks four expected source hashes before assigning this revision to any result.

```sh
python dem-validation/scripts/run_reproduction.py --source-dir /path/to/av-blocking-analysis --pudo-workbook "/path/to/ME 575 Class Final Data - PUDO - Waymo.xlsx" --output-dir /tmp/dem-recheck
python -m unittest discover -s dem-validation/tests -v
```

Without `--pudo-workbook`, the test states that PUDO inputs are cached. The supplied workbook was directly checked for the delivered result. No private medical narratives or meeting transcripts are published in this module.

## Sources and contribution

DEM data originate in the San Francisco DEM incident log, supplied and cleaned for the class by Dr Missy Cummings. The pinned public workbook copies, scope rules, hazard taxonomy, impact rubric and risk-matrix method are from Jonathan Wilson’s analysis. The source hashes in `scripts/verify_source.py` identify the actual copies; this audit does not independently certify their completeness or official provenance.

CJ Wu’s independent case questions helped separate logged duration from medical delay, explicit evidence from inferred obstruction, and blocking incidents from out-of-scope AV events. This module adds AI-assisted numerical verification, source tracing, a fixed duration-model comparison and readable class materials. Numerical reproducibility is not clinical outcome validation.

Technical references: [scikit-learn logistic regression](https://scikit-learn.org/stable/modules/linear_model.html#logistic-regression), [decision trees](https://scikit-learn.org/stable/modules/tree.html), [evaluation metrics](https://scikit-learn.org/stable/modules/model_evaluation.html), [SciPy Poisson](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.poisson.html) and [Gamma](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.gamma.html).

## 中文要点

课堂主要讲一页 DEM，PUDO 单独备用。我们新增的价值是核对原文与数字，以及检验现有字段能否预测长事件，而不是再复制一篇长论文。

H2 的严重后果是场景分级，不是证明已发生死亡或重伤。概率必须只数符合该后果层级的事件。仅明确证据时，评级由含推断口径的 Very high 变为 Medium；这说明证据规则会影响结果。

新增 24 条人工复核仍待填写。先各自记录类别、证据强度和实际/潜在后果，再保存分歧与共同裁决，最后按共同规则重算。unknown 不能自动改成 No。
