# OPT-1 P3 golden hash changes

Replacing the per-step `max`/`min` in `kd` with monotonic deques (OPT-1 P3) changes the source bytes of
`quantlab/indicators.py`. The analysis operations (`ui_analysis_preview`, `ui_analysis_read`, `ui_analysis_reconcile`,
`ui_analysis_run`) bind the SHA-256 of that file into the packet `implementation`, so exactly the 23 leaves below of
`tests/fixtures/ui_operations_golden.json` (the implementation hash and the ids/hashes derived from it) were
regenerated with the real isolated exercise of `tests/test_ui_operations_registry.py`, as for B3. Every changed
leaf is a SHA-256 value (or `analysis-` + SHA-256); no other leaf changed, and KD outputs are digit-identical
(see `KdMonotonicWindowEquivalenceTests` in `tests/test_indicators.py`). `tests/test_golden_metadata.py` re-pins
the two canonical digests of the fixture for this reason only.

| Leaf | Old | New |
|---|---|---|
| `ui_analysis_preview/result/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_preview/result/plan/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_preview/result/plan/binding/packet/implementation/indicators.py` | `c15bb866e4d4c714…` | `0a52871d55b7c6fa…` |
| `ui_analysis_preview/result/plan/binding/packet/packet_hash` | `083938c273ded381…` | `5179933d71c828c0…` |
| `ui_analysis_preview/result/receipt_snapshot/provider_descriptor_hash` | `6656fa21a8f28862…` | `97090a17326cf693…` |
| `ui_analysis_read/result/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_read/result/record/plan/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_read/result/record/plan/binding/packet/implementation/indicators.py` | `c15bb866e4d4c714…` | `0a52871d55b7c6fa…` |
| `ui_analysis_read/result/record/plan/binding/packet/packet_hash` | `083938c273ded381…` | `5179933d71c828c0…` |
| `ui_analysis_read/result/record/provider_descriptor/campaign_id` | `analysis-1c5c953…` | `analysis-d72cd85…` |
| `ui_analysis_read/result/record/receipt_snapshot/provider_descriptor_hash` | `6656fa21a8f28862…` | `97090a17326cf693…` |
| `ui_analysis_reconcile/result/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_reconcile/result/record/plan/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_reconcile/result/record/plan/binding/packet/implementation/indicators.py` | `c15bb866e4d4c714…` | `0a52871d55b7c6fa…` |
| `ui_analysis_reconcile/result/record/plan/binding/packet/packet_hash` | `083938c273ded381…` | `5179933d71c828c0…` |
| `ui_analysis_reconcile/result/record/provider_descriptor/campaign_id` | `analysis-1c5c953…` | `analysis-d72cd85…` |
| `ui_analysis_reconcile/result/record/receipt_snapshot/provider_descriptor_hash` | `6656fa21a8f28862…` | `97090a17326cf693…` |
| `ui_analysis_run/result/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_run/result/record/plan/analysis_id` | `1c5c9531a825c637…` | `d72cd855b2536628…` |
| `ui_analysis_run/result/record/plan/binding/packet/implementation/indicators.py` | `c15bb866e4d4c714…` | `0a52871d55b7c6fa…` |
| `ui_analysis_run/result/record/plan/binding/packet/packet_hash` | `083938c273ded381…` | `5179933d71c828c0…` |
| `ui_analysis_run/result/record/provider_descriptor/campaign_id` | `analysis-1c5c953…` | `analysis-d72cd85…` |
| `ui_analysis_run/result/record/receipt_snapshot/provider_descriptor_hash` | `6656fa21a8f28862…` | `97090a17326cf693…` |
