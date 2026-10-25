"""LSTM that forecasts the next telemetry value from a window of SMAP inputs.

`forward` returns a prediction at every step. With quantiles it returns
(batch, time, Q): a low, a middle, and a high forecast, sorted into that
order. With `residual=True` each one is the current value plus its own
learned jump. Older checkpoints have no quantiles and return (batch, time).
"""

from __future__ import annotations

import torch
from torch import nn


class LSTMForecaster(nn.Module):
    def __init__(
        self,
        n_features: int = 25,
        hidden: int = 64,
        layers: int = 2,
        dropout: float = 0.2,
        residual: bool = False,
        quantiles: tuple[float, ...] = (),
    ):
        super().__init__()
        self.n_features = n_features
        self.hidden = hidden
        self.layers = layers
        self.dropout = dropout
        self.residual = residual
        self.quantiles = tuple(float(level) for level in quantiles)
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden,
            num_layers=layers,
            batch_first=True,
            dropout=dropout if layers > 1 else 0.0,
        )
        self.head = nn.Linear(hidden, max(1, len(self.quantiles)))
        if len(self.quantiles) == 3:
            with torch.no_grad():
                self.head.bias.copy_(torch.tensor([-0.2, 0.0, 1.0]))
        self._init_forget_bias()

    def _init_forget_bias(self) -> None:
        for name, param in self.lstm.named_parameters():
            if "bias_ih" in name:
                size = param.shape[0] // 4
                param.data[size : 2 * size].fill_(1.0)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        sequence, _ = self.lstm(inputs)
        raw = self.head(sequence)
        if not self.quantiles:
            predicted = raw.squeeze(-1)
            if self.residual:
                return inputs[..., 0] + predicted
            return predicted
        if self.residual:
            raw = inputs[..., 0].unsqueeze(-1) + raw
        return torch.sort(raw, dim=-1).values
