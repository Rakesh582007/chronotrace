"""Fine-tune DistilBERT to tag report rows (TEST / VALUE / UNIT / RANGE / FLAG).

Usage:  python ml/train_ner.py [--labels ml/generated/labels.jsonl] [--out ml/models/chronotrace-ner]

Trains on the "train" split, evaluates entity F1 (seqeval, strict IOB2) and loss on "val" after
each epoch and keeps the best epoch: highest val entity F1, ties broken by lower val loss. The "test" split (held-out layout families) is not touched
here; evaluate_ner.py reports it. Sized for a 6 GB RTX 3050: fp16, batch 32, 64 sub-tokens.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from seqeval.metrics import f1_score
from seqeval.scheme import IOB2
from torch.utils.data import DataLoader
from transformers import (AutoModelForTokenClassification, AutoTokenizer, DataCollatorForTokenClassification,
                          get_linear_schedule_with_warmup, set_seed)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ner_data as nd  # noqa: E402

ML = Path(__file__).resolve().parent
DEFAULT_OUT = ML / "models" / "chronotrace-ner"
HPARAMS = dict(base_model=nd.BASE_MODEL, max_length=nd.MAX_LENGTH, batch_size=32, lr=5e-5, epochs=3,
               weight_decay=0.01, warmup_ratio=0.0, fp16=True, seed=42)


def val_f1(model, tokenizer, rows, device) -> float:
    pred = nd.predict(model, tokenizer, rows, device, max_length=HPARAMS["max_length"])
    return f1_score([r["tags"] for r in rows], pred, mode="strict", scheme=IOB2)


def val_loss(model, loader, device, use_fp16: bool) -> float:
    """Mean cross-entropy per labelled word (first sub-tokens) over the val split."""
    model.eval()
    total, n = 0.0, 0
    with torch.no_grad():
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast(device.type, dtype=torch.float16, enabled=use_fp16):
                loss = model(**batch).loss
            k = int((batch["labels"] != nd.IGNORE).sum())
            total += loss.float().item() * k
            n += k
    return total / n


def is_better(f1: float, loss: float, best: dict) -> bool:
    """Higher val entity F1 wins; on a tie, lower val loss."""
    return f1 > best["val_f1"] or (f1 == best["val_f1"] and loss < best["val_loss"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train the report-row NER model.")
    ap.add_argument("--labels", type=Path, default=nd.DEFAULT_LABELS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    hp = HPARAMS

    set_seed(hp["seed"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_fp16 = hp["fp16"] and device.type == "cuda"
    print(f"device: {torch.cuda.get_device_name(0) if device.type == 'cuda' else 'cpu'}  fp16: {use_fp16}")

    tokenizer = AutoTokenizer.from_pretrained(hp["base_model"])
    model = AutoModelForTokenClassification.from_pretrained(
        hp["base_model"], num_labels=len(nd.LABELS), id2label=nd.ID2LABEL, label2id=nd.LABEL2ID).to(device)

    train_rows = nd.load_rows(args.labels, "train")
    val_rows = nd.load_rows(args.labels, "val")
    print(f"rows: train {len(train_rows)}, val {len(val_rows)}")
    loader = DataLoader(nd.NerDataset(tokenizer, train_rows, hp["max_length"]), batch_size=hp["batch_size"],
                        shuffle=True, num_workers=0, collate_fn=DataCollatorForTokenClassification(tokenizer),
                        generator=torch.Generator().manual_seed(hp["seed"]))
    val_loader = DataLoader(nd.NerDataset(tokenizer, val_rows, hp["max_length"]), batch_size=64, shuffle=False,
                            num_workers=0, collate_fn=DataCollatorForTokenClassification(tokenizer))

    no_decay = ("bias", "LayerNorm.weight")
    params = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)],
         "weight_decay": hp["weight_decay"]},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = torch.optim.AdamW(params, lr=hp["lr"])
    steps = len(loader) * hp["epochs"]
    scheduler = get_linear_schedule_with_warmup(optimizer, int(hp["warmup_ratio"] * steps), steps)
    scaler = torch.amp.GradScaler("cuda", enabled=use_fp16)

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    epochs, best = [], {"epoch": 0, "val_f1": -1.0, "val_loss": float("inf")}
    for epoch in range(1, hp["epochs"] + 1):
        model.train()
        t0, total_loss = time.perf_counter(), 0.0
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast(device.type, dtype=torch.float16, enabled=use_fp16):
                loss = model(**batch).loss
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            total_loss += loss.item()
        f1 = val_f1(model, tokenizer, val_rows, device)
        vloss = val_loss(model, val_loader, device, use_fp16)
        ep = {"epoch": epoch, "train_loss": round(total_loss / len(loader), 5), "val_loss": round(vloss, 6),
              "val_entity_f1": round(f1, 5), "seconds": round(time.perf_counter() - t0, 1)}
        epochs.append(ep)
        kept = is_better(f1, vloss, best)
        if kept:
            best = {"epoch": epoch, "val_f1": f1, "val_loss": vloss}
            model.save_pretrained(args.out)
            tokenizer.save_pretrained(args.out)
        print(f"epoch {epoch}/{hp['epochs']}: train loss {ep['train_loss']:.4f}  val loss {vloss:.6f}  "
              f"val entity F1 {f1:.4f}  ({ep['seconds']:.0f} s){'  <- saved' if kept else ''}")

    log = {
        "hyperparameters": hp,
        "device": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
        "train_rows": len(train_rows), "val_rows": len(val_rows), "steps": steps,
        "epochs": epochs, "selection": "highest val entity F1, ties broken by lower val loss",
        "best_epoch": best["epoch"], "best_val_entity_f1": round(best["val_f1"], 5),
        "best_val_loss": round(best["val_loss"], 6),
        "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if device.type == "cuda" else None,
        "train_seconds": round(time.perf_counter() - start, 1),
        "torch": torch.__version__,
    }
    (args.out / "training_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"best epoch {best['epoch']} (val entity F1 {best['val_f1']:.4f}, val loss {best['val_loss']:.6f}); "
          f"saved to {args.out}")
    print(f"peak VRAM {log['peak_vram_mb']} MB; training time {log['train_seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
