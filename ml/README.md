# ml/ — Phase 0: ML research on SWELL-KW

This folder holds the notebooks that explore SWELL-KW, build features, train and evaluate the models,
and export them for the app.

```
ml/
├── data/raw/          SWELL files (placed by hand, not in git)
├── data/processed/    files written by the notebooks (not in git)
├── data/own/          our own exported study data, later (not in git)
├── notebooks/
│   ├── 01_eda.ipynb        load, clean, join self-ratings, explore
│   ├── 02_features.ipynb   SWELL → our feature names, features, labels, normalisation
│   ├── 03_models.ipynb     LOSO evaluation, ablations, SHAP, export to shared/models/
│   └── 04_own_data.ipynb   our own study data (skips itself until data exists)
└── reports/           charts and tables for the college report
```

## How to run

```bash
# from the project root
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# open in Jupyter / VS Code and run in order, or run all from the command line:
jupyter nbconvert --to notebook --execute --inplace ml/notebooks/01_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace ml/notebooks/02_features.ipynb
jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=7200 ml/notebooks/03_models.ipynb
jupyter nbconvert --to notebook --execute --inplace ml/notebooks/04_own_data.ipynb
```

Notebook 3 takes about 15–30 minutes (many cross-validation runs).

## Raw files used (`ml/data/raw/`)

Source: SWELL-KW, DANS archive https://doi.org/10.17026/dans-x55-69zp (CC-BY-NC-SA-4.0). Not the Kaggle "SWELL" (HRV) dataset.

| File | Used for |
|---|---|
| `3 - Feature dataset/per sensor/A - Computer interaction features (Ulog - All Features per minute).xlsx`, sheet **`Sheet1`** | the per-minute computer-interaction rows |
| `Behavioral-features - per minute.xlsx`, sheet **`SWELLdata`** | **only** the questionnaire columns (self-ratings). All facial, posture and physiology columns are ignored. |
| `SWELL-KW - overview available data.xlsx` | reference only: which recordings worked |
| `Manual KW Dataset .docx` | reference only: dataset description |

### Sheets of the computer-interaction workbook

| Sheet | Shape | Content | Used? |
|---|---|---|---|
| `Sheet1` | 3,139 rows × 20 columns | one row per participant-minute | **yes** |
| `Sheet2` | 81 rows × 9 columns + notes | session schedule per block (start/end times, film and task length, Dutch notes); includes pilot participants SP and MP | no (reference) |
| `Sheet3` | 3,140 rows × 21 columns | older copy of Sheet1: `SnMouseDistance` appears twice, the first copy lost its decimal point (e.g. `2.83e16` instead of `28311.9`); has one extra row (PP3, block 2, labelled N) that contradicts the schedule | no |

The CSV/ODS files next to the workbook are exports of these sheets (`-Sheet_1.csv` = Sheet1).

### Real column names in `Sheet1`

| Column | Meaning (from the SWELL documentation) |
|---|---|
| `PP` | participant, `PP1` … `PP25` |
| `Blok` | block 1, 2, 3 (order performed; block 1 is always neutral) |
| `Condition` | `N` neutral, `I` interruptions, `T` time pressure, `R` relax (short film before each block) |
| `timestamp` | start of the minute, text like `20120918T131600000` |
| `SnMouseAct` | number of all mouse events |
| `SnLeftClicked` | left clicks |
| `SnRightClicked` | right clicks |
| `SnDoubleClicked` | double clicks |
| `SnWheel` | mouse-wheel scroll events |
| `SnDragged` | mouse drag events |
| `SnMouseDistance` | distance the mouse moved |
| `SnKeyStrokes` | all key events (always = `SnChars` + `SnSpecialKeys`) |
| `SnChars` | letters typed (a–z) |
| `SnSpecialKeys` | non-letter keys |
| `SnDirectionKeys` | arrow keys |
| `SnErrorKeys` | backspace, delete, Ctrl+Z |
| `SnShortcutKeys` | Ctrl+C/X/V/Z/S/A, Shift+Tab |
| `SnSpaces` | spaces |
| `SnAppChange` | application changes |
| `SnTabfocusChange` | tab-focus changes |

### Questionnaire columns taken from `SWELLdata`

One rating per participant per condition (repeated on every minute of the block); none for relax.
`MentalEffort` (RSME, used for the load label), `Stress`, `NasaTLX` (missing for PP15), the NASA-TLX sub-scales
`MentalDemand`, `PhysicalDemand`, `TemporalDemand`, `Effort`, `Performance_rc`, `Frustration`, and the SAM scales
`Valence_rc`, `Arousal_rc`, `Dominance` (`_rc` = recoded).

## Data cleaning decisions

| Issue | Rows | Decision |
|---|---|---|
| uLog crash: every column = `999` (PP11 block 3 I: 21; PP16 block 2 I: 10) | 31 | removed |
| `#VALUE!` in `SnMouseDistance` (PP11 N, PP17 I) | 2 | removed |
| Relax (R) minutes: film, almost all zero | 451 | kept in `swell_clean.csv`, not used for models |
| Idle minutes (no keyboard/mouse input) in N/I/T | 37 | not used for training/testing (the app only predicts in active minutes) |
| Each person's first 15 active minutes (calibration) | 375 | used as the personal baseline, not for training/testing |
| PP12 and PP21 did not see the interruption e-mails (schedule notes) | – | kept, flagged as a limitation |

Result: 3,106 clean minutes → 2,655 N/I/T minutes → **2,243 modelling minutes** (neutral 630, interruptions 951, time pressure 662).

## Feature parity mapping (SWELL → our agent)

Only signals our desktop agent can also log are used.

| Our raw count | SWELL column(s) | Difference |
|---|---|---|
| `keystrokes` | `SnKeyStrokes` | – |
| `error_keys` | `SnErrorKeys` | SWELL also counts Ctrl+Z; we count backspace + delete |
| `shortcut_keys` | `SnShortcutKeys` | SWELL: fixed list of shortcuts; we: any key while Cmd/Ctrl/Alt is held |
| `clicks` | `SnLeftClicked` + `SnRightClicked` | – |
| `scrolls` | `SnWheel` | – |
| `mouse_distance` | `SnMouseDistance` | units depend on the screen; per-person z-scores remove the scale |
| `app_switches` | `SnAppChange` | – |

Not used, because our agent does not log them: `SnMouseAct`, `SnDoubleClicked`, `SnDragged`, `SnChars`,
`SnSpecialKeys`, `SnDirectionKeys`, `SnSpaces`, `SnTabfocusChange`.
Our agent's `pause_count`, `pause_total_seconds` and `active_seconds` do not exist in SWELL, so the models cannot use them.

From these 7 counts, `shared/features.py` builds 52 model features:
3 ratios (`error_key_ratio`, `shortcut_ratio`, `keyboard_share`), and for 3- and 5-minute trailing windows the rolling
mean and standard deviation of all 10 per-minute features plus the share of idle minutes. All are z-scored
against the person's first 15 active minutes.

## Labels

* `condition`: neutral / interruptions / time_pressure; `stressed`: I or T = 1, N = 0.
* `load_person_median` (main): high if the block's MentalEffort is above that person's own median of their 3 ratings.
* `load_overall_median`: high if above the median of all 75 block ratings (5.7).

## Results

See `shared/models/model_card.md` (generated by Notebook 3) and the tables/charts in `ml/reports/`.
