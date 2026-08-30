"""
train_baseline.py
-----------------
TF-IDF + logistic regression on ml/dataset.csv. Trains in seconds, no GPU.

    python ml/train_baseline.py                     # fake detection
    python ml/train_baseline.py --target contradiction

Why start here and not with a transformer
-----------------------------------------
This baseline is the number a fine-tuned DistilBERT has to beat to have
earned its place. Without it, "our model got 94%" is unanswerable - 94% of
what? A logistic regression that also gets 94% means the transformer added
nothing but four hours and a GPU bill.

It is also readable. `--top-features` prints the exact words driving each
prediction, which is how you catch a leak that the dataset checks missed:
if the strongest signal for "fake" turns out to be `bit` and `ly`, the model
found our fake-link decoration, not our writing style.

The split comes from the `split` column in the CSV - already grouped by
dedup_hash so near-duplicates can't straddle train and test.
"""

import argparse
import csv
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "dataset.csv")

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (classification_report, confusion_matrix,
                                 roc_auc_score)
    from sklearn.dummy import DummyClassifier
except ImportError:
    sys.exit("scikit-learn missing.  pip install scikit-learn")


def load(target):
    if not os.path.exists(CSV_PATH):
        sys.exit(f"{CSV_PATH} not found - run build_dataset.py first")
    train, test = [], []
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row[target] == "":
                continue
            item = (row["text"], int(row[target]))
            (train if row["split"] == "train" else test).append(item)
    return train, test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="ml_label",
                    choices=["ml_label", "contradiction"])
    ap.add_argument("--top-features", type=int, default=15)
    args = ap.parse_args()

    train, test = load(args.target)
    if len(train) < 20 or len(test) < 10:
        sys.exit(f"not enough labelled rows for '{args.target}' "
                 f"(train {len(train)}, test {len(test)})")

    Xtr, ytr = [t for t, _ in train], [y for _, y in train]
    Xte, yte = [t for t, _ in test], [y for _, y in test]

    print("=" * 60)
    print(f"TARGET: {args.target}")
    print("=" * 60)
    print(f"train {len(ytr)}  {dict(Counter(ytr))}")
    print(f"test  {len(yte)}  {dict(Counter(yte))}")

    # Always-predict-the-majority-class. Any real model must beat this, and
    # on an unbalanced set it can be embarrassingly high on its own.
    dummy = DummyClassifier(strategy="most_frequent").fit(Xtr, ytr)
    print(f"\nmajority-class baseline: {dummy.score(Xte, yte):.3f}")

    # Word + character n-grams. Characters catch the punctuation and casing
    # habits that word tokens miss (ALL CAPS, "!!!", odd spacing).
    vec = TfidfVectorizer(
        sublinear_tf=True, min_df=2, ngram_range=(1, 2),
        strip_accents="unicode", lowercase=True,
    )
    Vtr = vec.fit_transform(Xtr)
    Vte = vec.transform(Xte)

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(Vtr, ytr)

    pred = clf.predict(Vte)
    acc = clf.score(Vte, yte)
    print(f"\naccuracy: {acc:.3f}")
    if len(set(yte)) > 1:
        proba = clf.predict_proba(Vte)[:, 1]
        print(f"roc auc:  {roc_auc_score(yte, proba):.3f}")

    print("\n" + classification_report(yte, pred, digits=3, zero_division=0))

    cm = confusion_matrix(yte, pred)
    print("confusion matrix   (rows = truth, cols = predicted)")
    print("            pred 0   pred 1")
    for i, r in enumerate(cm):
        print(f"  true {i}   {r[0]:>6}   {r[1]:>6}")

    if args.top_features:
        names = vec.get_feature_names_out()
        coefs = clf.coef_[0]
        order = coefs.argsort()
        print(f"\ntop {args.top_features} words pushing toward class 1")
        for i in order[::-1][:args.top_features]:
            print(f"  {coefs[i]:+.2f}  {names[i]}")
        print(f"\ntop {args.top_features} words pushing toward class 0")
        for i in order[:args.top_features]:
            print(f"  {coefs[i]:+.2f}  {names[i]}")

    if acc > 0.95:
        print("\n" + "!" * 60)
        print("Accuracy above 95% on a dataset this size is almost always a")
        print("leak, not a result. Read the top features above: if they are")
        print("artefacts (link fragments, punctuation, a stock phrase) rather")
        print("than meaning, the model found a shortcut. Fix the data.")
        print("!" * 60)


if __name__ == "__main__":
    main()
