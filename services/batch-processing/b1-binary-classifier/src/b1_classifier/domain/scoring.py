"""One number per session: how likely the B1 model thinks it is violating."""
from b1_classifier.domain.features import session_features


def violating_probability(model, calls: list[dict]) -> float:
    classes = list(model.classes_)
    probabilities = model.predict_proba([session_features(calls)])[0]
    return float(probabilities[classes.index("violating")])