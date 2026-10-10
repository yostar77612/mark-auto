"""Deterministic offline OHLC research engine, never a liquidity/broker simulator.

Futures accounting keeps notional out of cash. FIFO matched lots carry allocated
entry costs. Explicit daily MTM and scheduled two-contract rolls require versioned inputs.
"""
from collections import defaultdict
from pathlib import Path
import hashlib
import platform
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, ROUND_CEILING, ROUND_HALF_EVEN, Context, localcontext
from .core import (BacktestConfig, BacktestResult, CostSpec, Dataset, Fill,
                   ValidationError, content_hash, validate_date, validate_decimal, validate_utc, validate_contract, to_dict)
from .strategies import generate_signals, validate_strategy, _validate_bars

ENGINE_VERSION = 'quantlab-event-v1'
MULTIPLIER = Decimal('10')
ROUNDINGS = {'none': None, 'floor_twd': ROUND_FLOOR, 'half_up_twd': ROUND_HALF_UP, 'ceiling_twd': ROUND_CEILING}


def _performance_metrics(ledger, equity, initial_cash):
    """Descriptive report math; does not affect execution or candidate selection.

    Closed FIFO matches include their allocated entry/exit costs and full-trade
    PnL (not merely the exit cash delta after daily MTM). Sharpe uses the last
    supplied equity per exchange trading date, including initial cash -> first
    date. Missing dates are not imputed. Two observations is a mathematical
    minimum, never a statistical sufficiency or strategy-qualification claim.
    """
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        closed = [row['net_pnl'] for row in ledger]
        gains = sum((pnl for pnl in closed if pnl > 0), Decimal('0'))
        losses = -sum((pnl for pnl in closed if pnl < 0), Decimal('0'))
        factor_reason = 'no closed lots' if not closed else 'no losing closed lots' if not losses else None
        daily = {}
        for row in equity:
            daily[row['trade_date']] = row.get('equity')
        previous = initial_cash
        returns = []
        for day, value in daily.items():
            valid = all(isinstance(x, Decimal) and x.is_finite() for x in (previous, value))
            reason = ('missing or non-finite equity' if not valid else
                      'nonpositive equity at return boundary' if min(previous, value) <= 0 else None)
            returns.append({'trade_date': day, 'return': value / previous - 1 if reason is None else None,
                            'reason': reason})
            previous = value
        values = [row['return'] for row in returns]
        sharpe, reason = None, None
        if any(value is None for value in values):
            reason = 'missing or nonpositive daily equity; no observations discarded'
        elif len(values) < 2:
            reason = 'at least 2 daily returns required for sample standard deviation'
        else:
            mean = sum(values, Decimal('0')) / len(values)
            variance = sum(((value - mean) ** 2 for value in values), Decimal('0')) / (len(values) - 1)
            if not variance:
                reason = 'zero daily-return sample variance'
            else:
                sharpe = mean / variance.sqrt() * Decimal(252).sqrt()
        return {
            'profit_factor': gains / losses if factor_reason is None else None,
            'profit_factor_reason': factor_reason,
            'profit_factor_basis': 'closed FIFO lot net PnL after allocated entry/exit costs; open lots excluded',
            'daily_returns': returns, 'sharpe': sharpe, 'sharpe_reason': reason,
            'sharpe_observations': len(values),
            'sharpe_sample_count': sum(value is not None for value in values),
            'sharpe_note': 'Descriptive only. Two returns is a mathematical minimum, not evidence of reliability; short samples do not establish strategy quality. The 252-period convention is assumed, not a validated annual trading calendar; gaps may span multiple days.',
            'annualization': {
                'periods_per_year': 252, 'annual_risk_free_rate': Decimal('0'),
                'return_frequency': 'between last supplied equity per exchange trading date; gaps may span multiple days',
                'first_return': 'initial cash to first supplied trading-date equity',
                'missing_dates': 'supplied trading dates only; no imputation',
                'standard_deviation': 'sample (ddof=1)', 'minimum_observations': 2,
            },
        }


def calculate_costs(price, quantity, costs):
    """Per-fill tax on total quantity; versioned rounding is an explicit assumption."""
    if costs.tax_rounding not in ROUNDINGS:
        raise ValidationError('unsupported tax rounding policy')
    commission = costs.commission_per_side * quantity
    tax = price * MULTIPLIER * quantity * costs.tax_rate
    if ROUNDINGS[costs.tax_rounding]: tax = tax.quantize(Decimal('1'), rounding=ROUNDINGS[costs.tax_rounding])
    return commission, tax


def _cost_at(config, trade_date):
    schedule = (config.costs,) + tuple(config.cost_schedule)
    if any(not isinstance(c, CostSpec) for c in schedule): raise ValidationError('invalid cost schedule')
    dates = [c.effective_from for c in schedule]
    if len(set(dates)) != len(dates): raise ValidationError('duplicate cost effective dates')
    for cost in schedule:
        if not isinstance(cost, CostSpec): raise ValidationError('invalid cost schedule')
        cost.__post_init__()
        if cost.tax_rounding not in ROUNDINGS: raise ValidationError('unsupported tax rounding policy')
    applicable = [c for c in schedule if c.effective_from <= trade_date]
    if not applicable: raise ValidationError('no effective cost schedule')
    return max(applicable, key=lambda c:c.effective_from)


def _margin_at(config, trade_date):
    initial, maintenance, version = config.initial_margin_per_contract, config.maintenance_margin_per_contract, config.margin_version
    previous = set()
    if any(not isinstance(r,dict) for r in config.margin_schedule): raise ValidationError('invalid margin schedule')
    for row in sorted(config.margin_schedule, key=lambda r:r.get('effective_from','')):
        if set(row) != {'effective_from','initial_margin','maintenance_margin','version'}:
            raise ValidationError('margin schedule requires effective_from/initial_margin/maintenance_margin/version')
        validate_date(row['effective_from'])
        if row['effective_from'] in previous: raise ValidationError('duplicate margin effective dates')
        previous.add(row['effective_from'])
        for key in ('initial_margin','maintenance_margin'): validate_decimal(row[key],key,Decimal('0'))
        if not row['version'] or row['maintenance_margin'] > row['initial_margin']: raise ValidationError('invalid margin schedule')
        if row['effective_from'] <= trade_date:
            initial,maintenance,version=row['initial_margin'],row['maintenance_margin'],row['version']
    if initial is None or not version: raise ValidationError('explicit versioned margin required; historical margin is not inferred')
    validate_decimal(initial,'initial_margin',Decimal('0'))
    if maintenance is not None:
        validate_decimal(maintenance,'maintenance_margin',Decimal('0'))
        if maintenance>initial: raise ValidationError('maintenance exceeds initial margin')
    return initial,maintenance,version


def run_backtest(dataset, spec, config):
    # Caller Decimal precision must not alter replay hashes.
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        return _run(dataset,spec,config)


def _run(dataset,spec,config):
    if not isinstance(dataset,Dataset) or not isinstance(config,BacktestConfig): raise ValidationError('Dataset and BacktestConfig required')
    config.__post_init__(); validate_strategy(spec); _validate_bars(dataset.bars)
    if dataset.quality.get('valid') is not True or dataset.quality.get('errors') or dataset.quality.get('missing_intervals',0):
        raise ValidationError('data quality invalid or unverified')
    if dataset.manifest.get('validation_status') != 'valid': raise ValidationError('data validation status not valid')
    actual_hash=content_hash(dataset.bars)
    if dataset.manifest.get('data_hash') != actual_hash: raise ValidationError('data hash missing or mismatched')
    if dataset.manifest.get('source_type') not in ('synthetic','proxy','official_local'): raise ValidationError('data source type required')
    if config.settlement_mode not in ('unsettled_pnl','daily_mtm'): raise ValidationError('unsupported settlement mode')
    if not dataset.bars: raise ValidationError('empty dataset')
    contracts={b.contract_id for b in dataset.bars}
    for contract,expiry in config.instrument_expiries.items():
        validate_contract(contract); validate_date(expiry)
    groups=defaultdict(dict)
    for b in dataset.bars:
        if min(b.open,b.high,b.low,b.close)<=0: raise ValidationError('nonpositive market price')
        groups[b.timestamp][b.contract_id]=b
    roll_map={}
    for event in config.roll_events:
        if not isinstance(event,dict) or set(event)!={'known_at','effective_at','from_contract','to_contract'}:
            raise ValidationError('explicit roll requires known_at/effective_at/from_contract/to_contract')
        validate_utc(event['known_at']); validate_utc(event['effective_at'])
        validate_contract(event['from_contract']); validate_contract(event['to_contract'])
        if event['known_at']>event['effective_at'] or event['from_contract']==event['to_contract']:
            raise ValidationError('roll must be known before execution, between distinct contracts')
        when=event['effective_at']
        if when in roll_map: raise ValidationError('duplicate roll event')
        pair=groups.get(when,{})
        if any(c not in pair or pair[c].volume<=0 for c in (event['from_contract'],event['to_contract'])):
            raise ValidationError('BLOCKED: roll requires simultaneous tradable real-contract bars')
        if pair[event['from_contract']].trade_date!=pair[event['to_contract']].trade_date or pair[event['from_contract']].end!=pair[event['to_contract']].end:
            raise ValidationError('roll bars must have matching trading date and interval')
        roll_map[when]=event
    if len(contracts)>1 and not roll_map: raise ValidationError('BLOCKED: multi-contract data requires explicit roll schedule')
    active_contract=(min(roll_map.items())[1]['from_contract'] if roll_map else dataset.bars[0].contract_id)
    if active_contract not in groups[dataset.bars[0].timestamp]: raise ValidationError('initial active contract missing')
    settlement_map={}; final_times={}
    for event in config.settlement_events:
        if not isinstance(event,dict): raise ValidationError('invalid settlement event')
        base_keys={'timestamp','known_at','contract_id','price','version'}
        kind=event.get('kind','daily')
        allowed=base_keys|({'kind'} if 'kind' in event else set())
        if kind=='final': allowed|={'settlement_fee_per_contract','settlement_tax_rate','tax_rounding'}
        if set(event)!=allowed or kind not in ('daily','final'):
            raise ValidationError('invalid settlement event keys or kind')
        validate_utc(event['timestamp']); validate_utc(event['known_at']); validate_contract(event['contract_id'])
        validate_decimal(event['price'],'settlement price',Decimal('0'))
        if not event['price'] or not isinstance(event['version'],str) or not event['version'] or event['known_at']>event['timestamp']:
            raise ValidationError('invalid or future-known settlement')
        key=(event['timestamp'],event['contract_id'])
        if key in settlement_map: raise ValidationError('duplicate settlement')
        matching=[b for b in dataset.bars if b.end==key[0] and b.contract_id==key[1]]
        if len(matching)!=1: raise ValidationError('settlement timestamp must equal supplied bar close availability')
        if kind=='final':
            if config.instrument_expiries.get(key[1])!=matching[0].trade_date:
                raise ValidationError('final settlement requires matching explicit expiry trading date')
            validate_decimal(event['settlement_fee_per_contract'],'settlement fee',Decimal('0'))
            validate_decimal(event['settlement_tax_rate'],'settlement tax',Decimal('0'))
            if event['tax_rounding'] not in ROUNDINGS: raise ValidationError('unsupported final tax rounding')
            if key[1] in final_times: raise ValidationError('duplicate final settlement')
            final_times[key[1]]=key[0]
        elif config.settlement_mode=='unsettled_pnl':
            raise ValidationError('daily settlement events require daily_mtm mode')
        settlement_map[key]=event
    if config.settlement_mode=='daily_mtm' and not settlement_map: raise ValidationError('daily MTM requires explicit versioned settlement prices')
    for b in dataset.bars:
        _cost_at(config,b.trade_date); _margin_at(config,b.trade_date)
        expiry=config.instrument_expiries.get(b.contract_id)
        if expiry:
            validate_date(expiry)
            if b.trade_date>expiry: raise ValidationError('bar after contract expiry')
            local_start=b.timestamp.astimezone(ZoneInfo('Asia/Taipei'))
            local_end=b.end.astimezone(ZoneInfo('Asia/Taipei'))
            if local_start.date().isoformat()>expiry or (local_start.date().isoformat()==expiry and (b.session=='night' or (local_end.hour,local_end.minute,local_end.second,local_end.microsecond)>(13,30,0,0))):
                raise ValidationError('expired contract cannot trade after expiry-day 13:30 or in expiry-day night session')
        if b.contract_id in final_times and b.timestamp>=final_times[b.contract_id]:
            raise ValidationError('bar after final cash settlement; expired contract cannot reopen')
    if dataset.manifest['source_type'] != 'synthetic' and any(b.contract_id not in config.instrument_expiries for b in dataset.bars):
        raise ValidationError('explicit instrument expiry required for real/proxy data')
    if not isinstance(config.source_commit,str) or not config.source_commit: raise ValidationError('source_commit must be an explicit string')
    signals=generate_signals(dataset.bars,spec)
    by_time=defaultdict(list)
    for s in signals: by_time[s.timestamp].append(s)
    cash=config.initial_cash; lots=[]; fills=[]; ledger=[]; equity=[]; rejects=[]; settlements=[]; rolls=[]
    previous_bar=None; settled_dates=set(); finalized=set()
    pending=None; forced=False; peak=config.initial_cash; max_dd=Decimal('0'); max_dd_pct=Decimal('0')
    realized_gross=Decimal('0'); total_costs=Decimal('0'); total_slippage=Decimal('0')
    warnings=['OHLC fills assume tradability; no order-book liquidity or partial-fill validation.',
              'Tax rounding is a configured per-fill assumption, not verified broker billing.',
              'Final settlement uses explicit configured fee/tax treatment; official broker treatment is not verified.',
              'Scheduled roll fills assume both contract opens executable; real legging/liquidity is not verified.']
    if config.source_commit=='unrecorded': warnings.append('Source commit unrecorded; exact adjacent module source hashes identify this run.')
    if dataset.manifest['source_type']=='synthetic': warnings.append('SYNTHETIC data: results do not validate real-market performance.')
    if config.maintenance_margin_per_contract is None and not config.margin_schedule:
        warnings.append('Maintenance-margin simulation excluded: no maintenance schedule supplied.')
    if config.settlement_mode=='unsettled_pnl': warnings.append('Daily MTM excluded; cash changes only on closes and costs.')
    def position(): return sum(l['side']*l['quantity'] for l in lots)
    def unrealized(price): return sum(((price-l['basis_price'])*MULTIPLIER*l['side']*l['quantity'] for l in lots),Decimal('0'))
    def reject(b,reason,target=None): rejects.append({'timestamp':b.timestamp,'reason':reason,'target_position':target})
    def execute(b,side,quantity,reference,reason,at_open=True,entry=False):
        nonlocal cash,realized_gross,total_costs,total_slippage
        costs=_cost_at(config,b.trade_date); price=reference+Decimal(side*costs.slippage_ticks)
        if price<=0: reject(b,'nonpositive adverse fill price'); return False
        commission,tax=calculate_costs(price,quantity,costs); expense=commission+tax
        if entry:
            initial,_,_=_margin_at(config,b.trade_date)
            # Include immediate spread/slippage loss against the available open.
            after_equity=cash-expense+unrealized(b.open)+(b.open-price)*MULTIPLIER*side*quantity
            if after_equity < initial*(abs(position())+quantity):
                reject(b,'insufficient cash or initial margin',side*quantity); return False
        index=len(fills)+1
        timestamp=b.timestamp if at_open else b.end
        identity={'index':index,'timestamp':timestamp,'contract':b.contract_id,'side':side,'quantity':quantity,'price':price,'reason':reason}
        fid=content_hash(identity)
        fill=Fill(fid,content_hash({'order':identity}),timestamp,b.contract_id,'buy' if side>0 else 'sell',quantity,price,commission,tax,reason)
        fills.append(fill); cash-=expense; total_costs+=expense; total_slippage+=Decimal(costs.slippage_ticks)*MULTIPLIER*quantity
        if entry:
            lots.append({'fill_id':fid,'price':price,'basis_price':price,'contract_id':b.contract_id,'side':side,'quantity':quantity,'entry_cost_per_contract':expense/quantity,'timestamp':timestamp})
        else:
            remaining=quantity
            while remaining:
                lot=lots[0]; matched=min(remaining,lot['quantity'])
                gross=(price-lot['price'])*MULTIPLIER*lot['side']*matched
                entry_cost=lot['entry_cost_per_contract']*matched; exit_cost=expense*matched/quantity
                cash_delta=(price-lot['basis_price'])*MULTIPLIER*lot['side']*matched
                cash+=cash_delta; realized_gross+=cash_delta
                ledger.append({'entry_fill_id':lot['fill_id'],'exit_fill_id':fid,'entry_timestamp':lot['timestamp'],'exit_timestamp':timestamp,'contract_id':b.contract_id,'side':'long' if lot['side']>0 else 'short','quantity':matched,'entry_price':lot['price'],'exit_price':price,'gross_pnl':gross,'cash_pnl_on_exit':cash_delta,'entry_cost':entry_cost,'exit_cost':exit_cost,'net_pnl':gross-entry_cost-exit_cost,'reason':reason})
                remaining-=matched; lot['quantity']-=matched
                if not lot['quantity']: lots.pop(0)
        return True
    for timestamp,group in groups.items():
        next_bar=group.get(active_contract)
        if previous_bar is not None and next_bar is not None and previous_bar.trade_date!=next_bar.trade_date and config.settlement_mode=='daily_mtm' and position() and (previous_bar.trade_date,previous_bar.contract_id) not in settled_dates:
            raise ValidationError('BLOCKED: overnight position lacks previous trading-date settlement')
        event=roll_map.get(timestamp)
        if event:
            if event['from_contract']!=active_contract: raise ValidationError('roll source is not current active contract')
            old_bar,new_bar=group[event['from_contract']],group[event['to_contract']]
            old_position=position(); first_fill=len(fills)
            if old_position:
                execute(old_bar,-(1 if old_position>0 else -1),abs(old_position),old_bar.open,'roll_close')
            active_contract=event['to_contract']; pending=None
            if old_position and not forced:
                execute(new_bar,1 if old_position>0 else -1,abs(old_position),new_bar.open,'roll_open',entry=True)
            rolls.append({'event':event,'fill_ids':tuple(f.fill_id for f in fills[first_fill:]),'position_before':old_position,'position_after':position(),'status':'complete' if position()==old_position else 'new_leg_rejected'})
        if active_contract not in group:
            raise ValidationError('BLOCKED: active real contract has missing bar; cannot stitch another contract')
        b=group[active_contract]
        # Pending orders were created only at an earlier bar's close.
        if b.volume>0:
            if forced:
                if position(): execute(b,-(1 if position()>0 else -1),abs(position()),b.open,'maintenance_liquidation')
                pending=None; forced=False
            elif pending is not None and pending.timestamp<=b.timestamp:
                target=pending.target_position
                if abs(target)>config.max_position: reject(b,'max position exceeded',target)
                else:
                    current=position()
                    if current and (target*current<=0 or abs(target)<abs(current)):
                        close_qty=abs(current) if target*current<=0 else abs(current)-abs(target)
                        execute(b,-(1 if current>0 else -1),close_qty,b.open,'target_close')
                    current=position()
                    if target and (not current or abs(target)>abs(current)):
                        execute(b,1 if target>0 else -1,abs(target)-abs(current),b.open,'target_open',entry=True)
                pending=None
            # Protective levels use each FIFO lot's own actual slipped entry.
            if position() and ('stop_ticks' in spec.parameters or 'target_ticks' in spec.parameters):
                # One order closes the position at the most conservative triggered lot level.
                side=1 if position()>0 else -1
                candidates=[]
                for lot in lots:
                    stop=lot['price']-side*spec.parameters['stop_ticks'] if 'stop_ticks' in spec.parameters else None
                    target=lot['price']+side*spec.parameters['target_ticks'] if 'target_ticks' in spec.parameters else None
                    stop_hit=stop is not None and (b.low<=stop if side>0 else b.high>=stop)
                    target_hit=target is not None and (b.high>=target if side>0 else b.low<=target)
                    target_gap=target_hit and (b.open>=target if side>0 else b.open<=target)
                    stop_gap=stop_hit and (b.open<=stop if side>0 else b.open>=stop)
                    if target_gap and not stop_gap:
                        candidates.append((b.open,'gap_target',True))
                    elif stop_hit:
                        gap=b.open<=stop if side>0 else b.open>=stop
                        candidates.append((b.open if gap else stop,'gap_stop' if gap else 'stop',gap))
                    elif target_hit:
                        gap=b.open>=target if side>0 else b.open<=target
                        candidates.append((b.open if gap else target,'gap_target' if gap else 'target',gap))
                    if stop_hit and target_hit and not target_gap and not stop_gap:
                        rejects.append({'timestamp':b.timestamp,'reason':'ambiguous stop/target: conservative stop first','target_position':0})
                if candidates:
                    ref,reason,gap=(min(candidates,key=lambda x:x[0]) if side>0 else max(candidates,key=lambda x:x[0]))
                    execute(b,-side,abs(position()),ref,reason,at_open=gap)
        settlement=settlement_map.get((b.end,b.contract_id))
        settlement_pnl=Decimal('0')
        if settlement:
            is_final=settlement.get('kind','daily')=='final'
            settlement_id=content_hash(settlement)
            held=abs(position())
            commission=tax=Decimal('0')
            if is_final:
                settlement_costs=CostSpec(settlement['settlement_fee_per_contract'],settlement['settlement_tax_rate'],0,settlement['tax_rounding'],b.trade_date,settlement['version'])
                commission,tax=calculate_costs(settlement['price'],held,settlement_costs)
            for lot in lots:
                delta=(settlement['price']-lot['basis_price'])*MULTIPLIER*lot['side']*lot['quantity']
                settlement_pnl+=delta
                if is_final:
                    gross=(settlement['price']-lot['price'])*MULTIPLIER*lot['side']*lot['quantity']
                    entry_cost=lot['entry_cost_per_contract']*lot['quantity']
                    exit_cost=(commission+tax)*lot['quantity']/held
                    ledger.append({'entry_fill_id':lot['fill_id'],'exit_fill_id':None,'exit_event_id':settlement_id,'exit_event_type':'final_settlement','entry_timestamp':lot['timestamp'],'exit_timestamp':b.end,'contract_id':b.contract_id,'side':'long' if lot['side']>0 else 'short','quantity':lot['quantity'],'entry_price':lot['price'],'exit_price':settlement['price'],'gross_pnl':gross,'cash_pnl_on_exit':delta,'entry_cost':entry_cost,'exit_cost':exit_cost,'net_pnl':gross-entry_cost-exit_cost,'reason':'final_settlement'})
                else:
                    lot['basis_price']=settlement['price']
            cash+=settlement_pnl-commission-tax; realized_gross+=settlement_pnl; total_costs+=commission+tax
            settlements.append({'event':settlement,'event_id':settlement_id,'cash_pnl':settlement_pnl,'commission':commission,'tax':tax,'position':position(),'kind':'final' if is_final else 'daily'})
            settled_dates.add((b.trade_date,b.contract_id))
            if is_final:
                lots.clear(); finalized.add(b.contract_id); pending=None; forced=False
        initial,maintenance,margin_version=_margin_at(config,b.trade_date)
        upnl=unrealized(b.close); value=cash+upnl
        peak=max(peak,value); dd=peak-value; max_dd=max(max_dd,dd)
        if peak>0: max_dd_pct=max(max_dd_pct,dd/peak)
        equity.append({'timestamp':b.end,'trade_date':b.trade_date,'cash':cash,'unrealized_pnl':upnl,'equity':value,'position':position(),'margin_required':initial*abs(position()),'margin_version':margin_version,'settlement_pnl':settlement_pnl,'contract_id':b.contract_id})
        if maintenance is not None and position() and value<maintenance*abs(position()):
            forced=True; rejects.append({'timestamp':b.end,'reason':'maintenance breach; liquidate next tradable open','target_position':0})
        for signal in by_time.get(b.end,[]):
            if signal.contract_id==active_contract:
                if signal.contract_id in finalized: rejects.append({'timestamp':signal.timestamp,'reason':'signal rejected: contract finally settled','target_position':signal.target_position})
                else: pending=signal
        previous_bar=b
    final=equity[-1]['equity']; closed=[l['net_pnl'] for l in ledger]
    if pending: rejects.append({'timestamp':pending.timestamp,'reason':'unfilled final close signal: no subsequent tradable open','target_position':pending.target_position})
    if forced: warnings.append('BLOCKED: maintenance liquidation pending beyond available data.')
    final_bar=previous_bar
    if position() and config.instrument_expiries.get(final_bar.contract_id)==final_bar.trade_date:
        raise ValidationError('BLOCKED: open expiry position requires explicit final cash settlement event')
    metrics={'initial_cash':config.initial_cash,'final_equity':final,'net_pnl':final-config.initial_cash,'realized_gross_pnl':realized_gross,'unrealized_pnl':equity[-1]['unrealized_pnl'],'total_costs':total_costs,'slippage_cost':total_slippage,'return':(final/config.initial_cash-1) if config.initial_cash else None,'max_drawdown':max_dd,'max_drawdown_pct':max_dd_pct,'closed_lots':len(ledger),'trade_count':len(ledger),'fill_count':len(fills),'win_rate':Decimal(sum(x>0 for x in closed))/len(closed) if closed else None,'win_rate_reason':None if closed else 'no closed lots','open_position':position(),'open_lots':tuple(dict(l) for l in lots),'settlements':tuple(settlements),'rolls':tuple(rolls)}
    metrics.update(_performance_metrics(ledger, equity, config.initial_cash))
    if not dataset.manifest.get('calendar_hash'): warnings.append('Calendar content hash unavailable; calendar version alone does not verify session provenance.')
    if config.settlement_mode=='daily_mtm' and position() and (final_bar.trade_date,final_bar.contract_id) not in settled_dates:
        warnings.append('Final available trading date has an open, not-yet-daily-settled position; marked to last close only.')
    source_hashes={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('core.py','data.py','strategies.py','backtest.py')}
    manifest={'dataset_manifest':{k:v for k,v in dataset.manifest.items() if k!='imported_at'},'config':to_dict(config),'strategy':to_dict(spec),'source_hashes':source_hashes,'python_version':platform.python_version(),'decimal_precision':34,'decimal_rounding':'ROUND_HALF_EVEN','schema_version':1,'engine_version':ENGINE_VERSION,'source_commit':config.source_commit,'engine_hash':content_hash(source_hashes),'config_hash':content_hash(config),'spec_hash':content_hash(spec),'data_hash':actual_hash,'dataset_manifest_hash':content_hash({k:v for k,v in dataset.manifest.items() if k!='imported_at'}),'calendar_hash':dataset.manifest.get('calendar_hash'),'calendar_version':dataset.manifest.get('calendar_version'),'cost_hash':content_hash((config.costs,)+tuple(config.cost_schedule)),'seed':config.seed,'source_type':dataset.manifest['source_type'],'settlement_mode':config.settlement_mode,'execution':'signal close -> next tradable open; adverse slippage; conservative OHLC stops','protective_scope':'whole position at most adverse triggered original-entry lot level','intrabar_fill_timestamp':'bar.end records interval availability; exact intrabar time unknown','liquidity_validation':'not_verified','final_settlement_status':'simulated_explicit' if final_times else 'not_requested','roll_status':'simulated_explicit' if roll_map else 'not_requested','maintenance_status':'simulated' if config.maintenance_margin_per_contract is not None or config.margin_schedule else 'excluded'}
    payload={'manifest':manifest,'signals':signals,'fills':fills,'ledger':ledger,'equity':equity,'metrics':metrics,'rejects':rejects,'warnings':warnings}
    manifest['reproducibility_hash']=content_hash(payload); manifest['run_hash']=manifest['reproducibility_hash']
    return BacktestResult(manifest,signals,tuple(fills),tuple(ledger),tuple(equity),metrics,tuple(rejects),tuple(warnings))
