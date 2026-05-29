"""heyi-eval 实测结果读取（radar×heyi-eval 合并的结果回流侧）。

radar 与 heyi-eval 同机运行；heyi-eval 把 project/skill lane 的每次
评测落在 ``{HEYI_EVAL_DATA}/{lane}_lane/runs/<run_id>/`` 下的
``state.json`` / ``report.json``。本包只读这些文件，归一化后供
``/api/eval/results`` 与「实测结果」前端页消费。
"""
from radar.eval.reader import (
    EvalResult,
    list_results,
    load_result_detail,
    resolve_artifact,
)

__all__ = [
    "EvalResult",
    "list_results",
    "load_result_detail",
    "resolve_artifact",
]
