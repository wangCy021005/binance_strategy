"""
AlphaGPT 加密版词汇表
特征(8) + 算子(19) = 27 个 token
"""
from .factors import FEATURE_NAMES, NUM_FEATURES


class _Vocab:
    def __init__(self):
        self.feature_names   = FEATURE_NAMES
        self.feature_count   = NUM_FEATURES
        self.operator_offset = NUM_FEATURES

        self._ops = [
            "ADD","SUB","MUL","DIV",
            "NEG","ABS","SIGN","SQR",
            "MAX3","MIN3","GATE",
            "DELAY1","DELAY3","DELAY5",
            "RANK","SCALE","DEMEAN",
            "MA5","MA10",
        ]

        self.token_names    = list(FEATURE_NAMES) + self._ops
        self.vocab_size     = len(self.token_names)
        self.operator_names = self._ops    # alphagpt.py 用这个名字
        self.size           = self.vocab_size  # alphagpt.py 用这个名字

    def __len__(self):
        return self.vocab_size


FORMULA_VOCAB = _Vocab()
