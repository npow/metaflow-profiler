"""Example Metaflow flow demonstrating @profile_card.

Tests both the pyinstrument and cprofile backends with workloads that
actually produce interesting flamegraph data.

Run:
    python example_flow.py run

View cards:
    python example_flow.py card get 2/train /tmp/train.html --id profile_card_train
    python example_flow.py card get 2/evaluate /tmp/eval.html --id profile_card_evaluate
"""

import math
import random
import time

from metaflow import FlowSpec
from metaflow import profile_card
from metaflow import step


def _fib(n: int) -> int:
    """Deliberately recursive to generate interesting call-tree depth."""
    if n <= 1:
        return n
    return _fib(n - 1) + _fib(n - 2)


def _matrix_dot(a, b):
    """Pure-Python matrix multiply (intentionally slow for flamegraph visibility)."""
    n = len(a)
    result = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            s = 0.0
            for k in range(n):
                s += a[i][k] * b[k][j]
            result[i][j] = s
    return result


def _make_matrix(n):
    return [[random.gauss(0, 1) for _ in range(n)] for _ in range(n)]


def _compute_stats(data):
    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n
    return mean, math.sqrt(variance)


class ProfileDemoFlow(FlowSpec):
    """Demonstrates @profile_card with two backends and distinct workloads."""

    # ── start: trivial setup, pyinstrument ──────────────────────────────────
    @profile_card(profiler="pyinstrument")
    @step
    def start(self):
        """Light setup — mostly just initialises state."""
        self.message = "Starting profile demo"
        self.config = {
            "epochs": 5,
            "matrix_size": 30,
            "sample_size": 200_000,
        }
        self.next(self.train)

    # ── train: CPU-intensive, pyinstrument ──────────────────────────────────
    @profile_card(profiler="pyinstrument", sample_interval=0.001, timeline_interval=0.2)
    @step
    def train(self):
        """CPU-intensive: matrix ops + fibonacci to show call-tree depth."""
        cfg = self.config
        losses = []

        for epoch in range(cfg["epochs"]):
            # Matrix multiply — shows in flamegraph as hot inner loops
            a = _make_matrix(cfg["matrix_size"])
            b = _make_matrix(cfg["matrix_size"])
            result = _matrix_dot(a, b)

            # Fibonacci — generates deep recursive call tree
            fib_val = _fib(28)

            # Compute stats on the result rows
            flat = [result[i][j] for i in range(len(result)) for j in range(len(result[0]))]
            mean, std = _compute_stats(flat)
            loss = abs(mean - fib_val / 1e6)
            losses.append(loss)

        self.losses = losses
        self.final_loss = losses[-1]
        self.next(self.evaluate)

    # ── evaluate: memory allocation, cprofile ──────────────────────────────
    @profile_card(profiler="cprofile", timeline_interval=0.3)
    @step
    def evaluate(self):
        """Mixed compute + memory — uses cprofile backend for deterministic counts."""
        # Allocate a moderately large dataset
        dataset = [random.gauss(0, 1) for _ in range(500_000)]

        # Run several passes over the data
        mean, std = _compute_stats(dataset)
        sorted_data = sorted(dataset)
        percentiles = {
            "p50": sorted_data[len(sorted_data) // 2],
            "p95": sorted_data[int(len(sorted_data) * 0.95)],
            "p99": sorted_data[int(len(sorted_data) * 0.99)],
        }

        self.mean = mean
        self.std = std
        self.percentiles = percentiles
        del dataset, sorted_data
        self.next(self.end)

    @step
    def end(self):
        print(f"Losses:     {[f'{l:.4f}' for l in self.losses]}")
        print(f"Final loss: {self.final_loss:.6f}")
        print(f"Mean: {self.mean:.6f}  Std: {self.std:.6f}")
        print(f"Percentiles: {self.percentiles}")


if __name__ == "__main__":
    ProfileDemoFlow()
