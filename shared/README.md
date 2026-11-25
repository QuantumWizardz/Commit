# shared/ — code used by both the ML notebooks and the desktop agent

| File | What it is |
|---|---|
| `features.py` | The **only** code that turns raw per-minute counts into model features (ratios, idle flag, 3/5-minute rolling features) and does per-person normalisation (calibration baseline, z-scores). Used by `ml/notebooks/02_features.ipynb` now and by the agent in Phase 1. |
| `models/condition_model.pkl` | Condition model (neutral / interruptions / time_pressure), a scikit-learn pipeline. |
| `models/load_model.pkl` | Load model (low / high); load score = 100 × probability of "high". |
| `models/features.json` | Exact feature names and order, rolling windows, calibration length, classes, library versions. |
| `models/model_card.md` | Dataset, features, LOSO results, ablations, limitations. |

The model files are created by `ml/notebooks/03_models.ipynb`.

## Using the models (Phase 1 outline)

```python
import json, joblib, pandas as pd
from shared import features as F

spec = json.load(open("shared/models/features.json"))
model = joblib.load("shared/models/condition_model.pkl")

built = F.build_features(recent_minutes, time_column="ts")          # last few minutes of raw counts
latest = F.apply_baseline(built.tail(1), user_baseline, spec["feature_names"])
probabilities = model.predict_proba(F.order_for_model(latest, spec["feature_names"]))
```

The app must install the same `scikit-learn` and `lightgbm` versions as listed in `features.json`.

Tests: `pytest` (see `tests/test_features.py`).
