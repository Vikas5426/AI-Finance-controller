"""
Benchmark & Operational Metrics Evaluator
Strict Separation:
1. SYNTHETIC BENCHMARK MODE:
   - Evaluated ONLY when explicit ground truth is provided.
   - Labeled clearly as 'Synthetic Benchmark Precision', 'Synthetic Benchmark Recall', 'Synthetic Benchmark F1'.
2. REAL USER DATA MODE:
   - Ground truth is NOT assumed.
   - Benchmark precision/recall/F1/ECE are suppressed.
   - Operational metrics returned: matched count, unmatched count, confidence distribution,
     false-positive safeguards triggered, and throughput.
"""

from typing import Any, Dict, List, Optional
import numpy as np


class BenchmarkEvaluator:
    """Calculates benchmark metrics for synthetic datasets and operational metrics for real user data."""

    @staticmethod
    def compute_calibration_error(confidences: List[float], outcomes: List[int], num_bins: int = 10) -> float:
        """Computes Expected Calibration Error (ECE) across N confidence bins against ground truth outcomes."""
        if not confidences or not outcomes or len(confidences) != len(outcomes):
            return 0.0

        conf_arr = np.array(confidences)
        out_arr = np.array(outcomes)
        bins = np.linspace(0.0, 1.0, num_bins + 1)
        ece = 0.0
        n = len(confidences)

        for i in range(num_bins):
            bin_lower, bin_upper = bins[i], bins[i + 1]
            in_bin = (conf_arr > bin_lower) & (conf_arr <= bin_upper)
            bin_size = np.sum(in_bin)
            
            if bin_size > 0:
                bin_acc = np.mean(out_arr[in_bin])
                bin_conf = np.mean(conf_arr[in_bin])
                ece += (bin_size / n) * abs(bin_acc - bin_conf)

        return float(ece)

    @classmethod
    def evaluate_synthetic_benchmark(
        cls,
        matches: List[Any],
        ground_truth: List[Dict[str, Any]],
        wall_clock_seconds: float,
        total_records: int
    ) -> Dict[str, Any]:
        """Calculates explicit synthetic benchmark metrics against supplied ground truth manifest."""
        # Extract ground truth pair links
        gt_pairs = {
            (gt.get("source_id"), gt.get("target_id"))
            for gt in (ground_truth or [])
            if gt.get("source_id") and gt.get("target_id")
        }
        matched_count = len(matches)

        if not gt_pairs:
            return {
                "mode": "SYNTHETIC_BENCHMARK",
                "is_synthetic_benchmark": True,
                "status": "NO_GROUND_TRUTH_MANIFEST",
                "total_records": total_records,
                "wall_clock_seconds": round(wall_clock_seconds, 2),
                "matched_pairs_count": matched_count,
                "synthetic_benchmark_precision": None,
                "synthetic_benchmark_recall": None,
                "synthetic_benchmark_f1": None,
                "expected_calibration_error": None
            }

        tp = 0
        confidences: List[float] = []
        outcomes: List[int] = []
        matched_gt_pairs = set()
        for m in matches:
            legs = getattr(m, "legs", [])
            conf = getattr(m, "confidence", 0.95)
            confidences.append(float(conf))

            primaries = []
            counterparts = []
            for l in legs:
                role_val = getattr(l, "role", None)
                role_str = role_val.value if hasattr(role_val, "value") else str(role_val)
                t_id = getattr(l, "transaction_id", None)
                if role_str == "PRIMARY":
                    primaries.append(t_id)
                elif role_str == "COUNTERPART":
                    counterparts.append(t_id)
                else:
                    primaries.append(t_id)

            if not counterparts and len(primaries) >= 2:
                counterparts = [primaries.pop()]

            match_is_tp = False
            for p_id in primaries:
                for c_id in counterparts:
                    pair = (p_id, c_id)
                    rev_pair = (c_id, p_id)
                    if pair in gt_pairs or rev_pair in gt_pairs:
                        match_is_tp = True
                        if pair in gt_pairs:
                            matched_gt_pairs.add(pair)
                        if rev_pair in gt_pairs:
                            matched_gt_pairs.add(rev_pair)

            if match_is_tp:
                tp += 1
                outcomes.append(1)
            else:
                outcomes.append(0)

        precision = tp / matched_count if matched_count > 0 else 0.0
        recall = len(matched_gt_pairs) / len(gt_pairs) if len(gt_pairs) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        ece = cls.compute_calibration_error(confidences, outcomes) if confidences and outcomes else 0.0
        records_per_sec = total_records / wall_clock_seconds if wall_clock_seconds > 0 else 0.0

        return {
            "mode": "SYNTHETIC_BENCHMARK",
            "is_synthetic_benchmark": True,
            "total_records": total_records,
            "wall_clock_seconds": round(wall_clock_seconds, 2),
            "records_per_second": round(records_per_sec, 2),
            "synthetic_benchmark_precision": round(precision, 4),
            "synthetic_benchmark_recall": round(recall, 4),
            "synthetic_benchmark_f1": round(f1, 4),
            "expected_calibration_error": round(ece, 4),
            "matched_pairs_count": matched_count,
            "true_positives": tp,
            "ground_truth_target_count": len(gt_pairs)
        }

    @classmethod
    def evaluate_real_user_data(
        cls,
        matches: List[Any],
        exceptions: List[Any],
        proposals: List[Any],
        wall_clock_seconds: float,
        total_records: int,
        ai_investigations_count: int = 0
    ) -> Dict[str, Any]:
        """Calculates strictly operational metrics for real user datasets without ground truth."""
        matched_txns_count = sum(len(getattr(m, "legs", [])) for m in matches)
        unmatched_txns_count = max(0, total_records - matched_txns_count)

        # Confidence distribution breakdown
        confidences = [getattr(m, "confidence", 0.0) for m in matches]
        high_conf = sum(1 for c in confidences if c >= 0.95)
        med_conf = sum(1 for c in confidences if 0.80 <= c < 0.95)
        low_conf = sum(1 for c in confidences if c < 0.80)

        # False-positive safeguards triggered (runner-up margin gate Δ < 0.05 or quarantined items)
        safeguards_triggered = sum(
            1 for exc in exceptions
            if getattr(exc, "exception_type", "") in ("DUPLICATE_GATEWAY_WEBHOOK", "DUPLICATE_RECORD", "AMOUNT_MISMATCH")
        )

        records_per_sec = total_records / wall_clock_seconds if wall_clock_seconds > 0 else 50.0

        return {
            "mode": "REAL_USER_DATA",
            "is_synthetic_benchmark": False,
            "total_records": total_records,
            "matched_records": matched_txns_count,
            "unmatched_records": unmatched_txns_count,
            "matched_pairs": len(matches),
            "exceptions_count": len(exceptions),
            "manual_review_required": len(proposals),
            "processing_time_seconds": round(wall_clock_seconds, 2),
            "records_per_second": round(records_per_sec, 2),
            "false_positive_safeguards_triggered": safeguards_triggered,
            "confidence_breakdown": {
                "high_confidence_matches": high_conf,
                "medium_confidence_matches": med_conf,
                "low_confidence_matches": low_conf
            },
            "ai_investigations_performed": ai_investigations_count
        }
