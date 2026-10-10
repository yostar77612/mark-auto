"""Record actual public-source availability, separately from offline quality gates.

No credentials, synthetic fallback or raw datasets are published. A BLOCKED result
is not acceptance: CI may continue building an explicitly incomplete preview.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantlab.market_providers import refresh_daily


def validate(output, *, loader=refresh_daily):
    rows = []
    with tempfile.TemporaryDirectory(prefix='markauto-public-history-') as temporary:
        for provider, required in (('twse', {'TAIEX'}), ('taifex', {'TX', 'MXF', 'TMF'})):
            try:
                result = loader(provider, Path(temporary), network_enabled=True)
                symbols = {series.instrument.symbol for series in result.series}
                passed = not result.stale and required <= symbols
                rows.append({'provider': provider, 'status': 'VERIFIED' if passed else 'BLOCKED',
                    'symbols': sorted(symbols), 'series_count': len(result.series),
                    'bar_count': sum(len(series.bars) for series in result.series),
                    'source_hashes': sorted({series.provenance.sha256 for series in result.series}),
                    'source_urls': sorted({series.provenance.source_url for series in result.series}),
                    'trade_dates': sorted({series.provenance.as_of for series in result.series}),
                    'modes': sorted({series.provenance.mode for series in result.series}),
                    'reason': '' if passed else 'Required symbols missing or only stale fallback available'})
            except Exception as exc:
                rows.append({'provider': provider, 'status': 'BLOCKED',
                             'reason': type(exc).__name__ + ': official source unavailable or failed validation'})
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'status': 'VERIFIED' if all(row['status'] == 'VERIFIED' for row in rows) else 'BLOCKED',
              'scope': 'Actual explicit public daily-source download and parser only; no realtime, UI or investment acceptance',
              'providers': rows}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    report = validate(sys.argv[1])
    print('Public-source diagnostic:', report['status'], '(does not replace product acceptance gates)')
