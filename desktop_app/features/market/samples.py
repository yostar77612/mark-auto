"""Pure offline demo market data for presentation."""

from desktop_app.strings.catalog import ui_text


def sample_market_series():
    from quantlab.market import MarketSeries

    'Project the existing invented demo into daily display bars, in memory only.'
    from datetime import datetime, timezone
    from quantlab.reporting import synthetic_dataset
    from quantlab.market import InstrumentRef, MarketBar, SourceProvenance

    data = synthetic_dataset(960)
    instrument = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:202601', '202601')
    days = sorted({bar.trade_date for bar in data.bars})
    bars = []
    for day in days:
        group = [bar for bar in data.bars if bar.trade_date == day]
        bars.append(
            MarketBar(
                instrument,
                day,
                'day',
                group[0].open,
                max((b.high for b in group)),
                min((b.low for b in group)),
                group[-1].close,
                sum((b.volume for b in group)),
                interval='1d',
                source_id='synthetic-v1',
            )
        )
    provenance = SourceProvenance(
        'sample:synthetic-v1',
        data.manifest['source_hash'],
        ui_text('market.sample_label'),
        'sample:synthetic-v1',
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        days[-1],
        days[0],
        days[-1],
        mode='offline',
        warnings=(ui_text('market.sample_label'),),
    )
    return MarketSeries(instrument, tuple(bars), provenance)
