"""AlphaGPT 加密版配置"""
import torch


class AlphaConfig:
    DEVICE = (torch.device("mps") if hasattr(torch.backends, "mps")
              and torch.backends.mps.is_available()
              else torch.device("cuda") if torch.cuda.is_available()
              else torch.device("cpu"))

    BATCH_SIZE      = 256     # 比A股版大（加密数据快，显存允许）
    TRAIN_STEPS     = 2000
    MAX_FORMULA_LEN = 12
    NUM_FEATURES    = 8       # 见 factors.py 的 FEATURE_NAMES
    SEQ_LEN         = 120     # 120根K线窗口（4h×120=20天历史）

    d_model  = 64
    n_heads  = 4
    n_layers = 3
    dropout  = 0.1

    # 加密回测参数
    COMM     = 0.0004   # taker 手续费
    BASE_FEE = COMM * 2  # 往返成本
