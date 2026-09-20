"""Run optional local decision models on a frozen sample-derived fixture.

No API calls, production writes, deployment, or model code generation. See
docs/TYPED_DECISIONS.md for pins, setup, scope, and interpretation.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from experiments.decision_cases import CRITERIA, INSTRUCTIONS, build_cases, fingerprint, model_text
from experiments.decision_metrics import choose_threshold, normalize, score

LAYA_SOURCE = "d113dca2512fb3eaca313534bc54c7162d87c1d4"
LAYA_WEIGHTS = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
LAYA_SHA256 = "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"
MINILM_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"


class LearnedModel:
    def __init__(self, training, embedding=False):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        self.encoder = None
        if embedding:
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2",
                                               revision=MINILM_REVISION, device="cpu", local_files_only=True)
        self.models = {}
        for task, labels in CRITERIA.items():
            rows = [case for case in training if case["task"] == task]
            texts = [model_text(case) for case in rows]
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
            features = (self.encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                        if self.encoder else vectorizer.fit_transform(texts))
            # Fixed hyperparameters; no tuning against the test or development set.
            classifier = LogisticRegression(C=10, max_iter=1000, random_state=17)
            classifier.fit(features, [case["label"] for case in rows])
            self.models[task] = (vectorizer, classifier)

    def predict(self, case, reverse=False):
        vectorizer, classifier = self.models[case["task"]]
        text = [model_text(case)]
        features = (self.encoder.encode(text, normalize_embeddings=True, show_progress_bar=False)
                    if self.encoder else vectorizer.transform(text))
        probs = classifier.predict_proba(features)[0]
        return dict(zip(classifier.classes_, map(float, probs))), {}


class LayaModel:
    def __init__(self, source, weights):
        commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if commit != LAYA_SOURCE:
            raise ValueError(f"Laya source must be pinned to {LAYA_SOURCE}")
        if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
            raise ValueError("Laya source has local modifications.")
        sys.path.insert(0, str(source.resolve()))
        from laya import Agent
        self.agent = Agent(str(weights.resolve()), device="cpu")

    def predict(self, case, reverse=False):
        task = case["task"]
        criteria = CRITERIA[task]
        if reverse:
            criteria = dict(reversed(list(criteria.items())))
        question = {"type": "choice", "instructions": INSTRUCTIONS[task], "criteria": criteria}
        answer = self.agent.predict(case["state"], {"decision": question})
        row = answer["answers"]["decision"]
        return row["probabilities"], {"reported_entropy_confidence": row["confidence"],
                                     "input_tokens": answer["usage"]["input_tokens"]}


def evaluate(model, cases):
    rows = []
    for case in cases:
        started = time.perf_counter()
        probabilities, extra = model.predict(case)
        probabilities = normalize(probabilities, CRITERIA[case["task"]])
        elapsed = (time.perf_counter() - started) * 1000
        rows.append({**case, "probabilities": probabilities,
                     "predicted": max(probabilities, key=probabilities.get), "latency_ms": elapsed, **extra})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=["word", "embedding", "laya"], default=["word"])
    parser.add_argument("--laya-source", type=Path)
    parser.add_argument("--laya-weights", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/typed-decisions.json"))
    args = parser.parse_args()
    if "laya" in args.models and (not args.laya_source or not args.laya_weights):
        parser.error("Laya requires --laya-source and --laya-weights local paths.")
    os.environ.update({"USE_TF": "0", "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"})
    # Bound parallel execution for comparable CPU runs; optional runtime imports.
    from threadpoolctl import threadpool_limits
    threadpool_limits(4)
    if any(name != "word" for name in args.models):
        import torch
        torch.set_num_threads(4)
    cases = build_cases()
    training = [case for case in cases if case["split"] == "train"]
    development = [case for case in cases if case["split"] == "development"]
    test = [case for case in cases if case["split"] == "test"]
    random.Random(17).shuffle(development)
    random.Random(29).shuffle(test)
    versions = {}
    for package in ["numpy", "scikit-learn", "torch", "transformers", "sentence-transformers", "safetensors"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    manifest = {"fixture_sha256": fingerprint(cases), "seed": 17,
                "python": platform.python_version(), "platform": platform.platform(),
                "machine": platform.machine(), "device": "cpu", "threads": 4,
                "laya_source_commit": LAYA_SOURCE, "laya_weights_revision": LAYA_WEIGHTS,
                "minilm_revision": MINILM_REVISION,
                "split_counts": dict(Counter(case["split"] for case in cases)),
                "latency_scope": "One warm sequential prediction including tokenization, local model, probability validation; excludes load, training, HTTP, database and crew engine.",
                "limitations": "Synthetic wording-family holdout with correlated repetitions, not real user corrections; not an end-to-end agent or an RL training reproduction.",
                "versions": versions}
    if "laya" in args.models:
        with (args.laya_weights / "model.safetensors").open("rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest["laya_weights_sha256"] = digest.hexdigest()
        if digest.hexdigest() != LAYA_SHA256:
            raise ValueError("Laya weights differ from the pinned experiment checkpoint.")
    report = {"manifest": manifest, "models": {}}
    for name in args.models:
        started = time.perf_counter()
        model = (LayaModel(args.laya_source, args.laya_weights) if name == "laya"
                 else LearnedModel(training, embedding=name == "embedding"))
        setup = time.perf_counter() - started
        # Warm up with training data; no evaluation data used for training.
        for task in CRITERIA:
            model.predict(next(case for case in training if case["task"] == task))
        dev_rows = evaluate(model, development)
        thresholds = {task: choose_threshold([row for row in dev_rows if row["task"] == task]) for task in CRITERIA}
        test_rows = evaluate(model, test)
        summaries = {task: score([row for row in test_rows if row["task"] == task], list(labels), thresholds[task])
                     for task, labels in CRITERIA.items()}
        robustness = []
        if name == "laya":
            # Same semantic request, reversed option order, once per test family.
            seen = set()
            for row in test_rows:
                if row["family"] in seen:
                    continue
                seen.add(row["family"])
                probs, _ = model.predict(row, reverse=True)
                probs = normalize(probs, CRITERIA[row["task"]])
                predicted = max(probs, key=probs.get)
                robustness.append({"case_id": row["id"], "original": row["predicted"],
                                   "reversed": predicted, "flipped": predicted != row["predicted"],
                                   "probabilities": probs})
        report["models"][name] = {"setup_and_training_seconds": setup,
                                  "training": "No domain training" if name == "laya" else "Synthetic train split labels only",
                                  "scores": summaries, "development": dev_rows, "test": test_rows,
                                  "option_order_probes": robustness}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"model": name, "scores": summaries}), flush=True)
        del model
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
