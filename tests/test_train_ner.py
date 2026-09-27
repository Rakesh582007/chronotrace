import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")

from train_ner import is_better  # noqa: E402

BEST = {"epoch": 1, "val_f1": 0.999, "val_loss": 0.01}


@pytest.mark.parametrize("f1, loss, better", [
    (1.0, 0.5, True),        # higher F1 wins even with higher loss
    (0.998, 0.001, False),   # lower F1 loses even with lower loss
    (0.999, 0.005, True),    # tie on F1: lower loss wins
    (0.999, 0.02, False),    # tie on F1: higher loss loses
    (0.999, 0.01, False),    # exact tie: keep the earlier epoch
])
def test_checkpoint_selection(f1, loss, better):
    assert is_better(f1, loss, BEST) is better


def test_first_epoch_is_always_kept():
    assert is_better(0.0, 9.9, {"epoch": 0, "val_f1": -1.0, "val_loss": float("inf")})
