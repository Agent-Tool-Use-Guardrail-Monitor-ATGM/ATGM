"""Training and evaluation of the binary classifier (compliant vs. violating)."""
from dataclasses import dataclass

from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MaxAbsScaler

CLASSES = ["compliant", "violating"]


def make_model(kind: str = "random_forest"):
    """class_weight='balanced': the classes are very uneven (few compliant sessions)."""
    if kind == "logistic_regression":
        classifier = LogisticRegression(class_weight="balanced", max_iter=2000)
        return make_pipeline(DictVectorizer(), MaxAbsScaler(), classifier)
    classifier = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=0)
    return make_pipeline(DictVectorizer(), classifier)


@dataclass
class Result:
    model: object
    metrics: dict


def train_and_evaluate(features: list[dict], labels: list[str], kind: str = "random_forest",
                       test_size: float = 0.25, seed: int = 0) -> Result:
    """Holds out a stratified test set, reports precision/recall/F1 per class, then refits on all data."""
    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=test_size, stratify=labels, random_state=seed)
    model = make_model(kind).fit(train_x, train_y)
    predicted = model.predict(test_x)
    report = classification_report(test_y, predicted, labels=CLASSES, output_dict=True, zero_division=0)
    metrics = {
        "model": kind,
        "n_sessions": len(labels),
        "n_train": len(train_y),
        "n_test": len(test_y),
        "class_counts": {label: labels.count(label) for label in CLASSES},
        "per_class": {label: {key: round(report[label][key], 3) for key in ("precision", "recall", "f1-score", "support")}
                      for label in CLASSES},
        "accuracy": round(report["accuracy"], 3),
        "macro_f1": round(report["macro avg"]["f1-score"], 3),
        # the test set has few compliant sessions, so 5-fold cross-validation gives a steadier number
        "cv5_macro_f1": round(float(cross_val_score(
            make_model(kind), features, labels, scoring="f1_macro",
            cv=StratifiedKFold(5, shuffle=True, random_state=seed)).mean()), 3),
        "confusion_matrix": {"labels": CLASSES,
                             "rows_true_cols_predicted": confusion_matrix(test_y, predicted, labels=CLASSES).tolist()},
    }
    final_model = make_model(kind).fit(features, labels)    # the saved model uses every session
    return Result(final_model, metrics)