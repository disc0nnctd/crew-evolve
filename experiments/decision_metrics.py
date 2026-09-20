"""Small, dependency-free metrics used by the optional model experiment."""
import math


def normalize(probabilities, labels):
    if set(probabilities) != set(labels):
        raise ValueError("Probability keys must match the fixed answer set.")
    values = [float(probabilities[label]) for label in labels]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Probabilities must be finite and nonnegative.")
    total = sum(values)
    if not math.isclose(total, 1, abs_tol=0.002):
        raise ValueError("Probabilities must sum to one (allowing output rounding).")
    return {label: value / total for label, value in zip(labels, values)}


def quantile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def choose_threshold(rows, minimum=10):
    """Development-only: maximize accepted count with zero observed mistakes.

    A small synthetic set cannot certify real-world error rates. None means
    abstain on every request; this is not a production promotion gate.
    """
    for threshold in sorted({max(row["probabilities"].values()) for row in rows}):
        accepted = [row for row in rows if max(row["probabilities"].values()) >= threshold]
        if len(accepted) >= minimum and all(row["predicted"] == row["label"] for row in accepted):
            return threshold
    return None


def score(rows, labels, threshold=None):
    if not rows:
        raise ValueError("Cannot score an empty evaluation.")
    count = len(rows)
    correct = [row["predicted"] == row["label"] for row in rows]
    confidence = [max(row["probabilities"].values()) for row in rows]
    confusion = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    brier = log_loss = 0.0
    for row in rows:
        confusion[row["label"]][row["predicted"]] += 1
        brier += sum((row["probabilities"][label] - (label == row["label"])) ** 2 for label in labels)
        log_loss -= math.log(max(row["probabilities"][row["label"]], 1e-15))
    ece = 0.0
    for bucket in range(10):
        indices = [i for i, value in enumerate(confidence) if min(9, int(value * 10)) == bucket]
        if indices:
            ece += abs(sum(confidence[i] for i in indices) - sum(correct[i] for i in indices)) / count
    accepted = [i for i, value in enumerate(confidence) if threshold is not None and value >= threshold]
    errors = sum(not correct[i] for i in accepted)
    positives = sum(row["label"] == "clarify" for row in rows)
    return {"cases": count, "families": len({row["family"] for row in rows}),
            "accuracy": sum(correct) / count, "brier_sum_per_case": brier / count,
            "log_loss": log_loss / count, "expected_calibration_error_10_bins": ece,
            "clarify_recall": confusion["clarify"]["clarify"] / positives if positives else None,
            "latency_ms_p50": quantile([row["latency_ms"] for row in rows], 0.5),
            "latency_ms_p95": quantile([row["latency_ms"] for row in rows], 0.95),
            "threshold_from_development": threshold, "accepted": len(accepted),
            "accepted_errors": errors, "coverage": len(accepted) / count,
            "accepted_error_rate": errors / len(accepted) if accepted else None,
            "confusion": confusion}
