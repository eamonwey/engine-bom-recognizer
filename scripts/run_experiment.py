# -*- coding: utf-8 -*-
"""实验运行脚本（等价于 python -m engine_bom.cli experiment）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_bom.experiment import run_experiment  # noqa: E402

if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else os.path.join("configs", "experiment_demo.yaml")
    summaries = run_experiment(spec)
    for s in summaries:
        print(s)
