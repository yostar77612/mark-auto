"""Presentation-only summaries; never grants paper execution permission."""

OPERATION_LABELS = dict(
    zip(
        (
            'demo',
            'import',
            'refresh',
            'market_refresh',
            'backtest',
            'campaign',
            'compare',
            'select',
            'disable',
            'paper_snapshot',
            'paper_reconcile',
            'paper_kill',
            'paper_replay',
            'paper_submit',
            'paper_cancel',
            'backup_create',
            'backup_restore',
            'analysis_preview',
            'analysis_run',
            'analysis_read',
            'analysis_reconcile',
            'walk_forward_preview',
            'walk_forward_run',
            'walk_forward_read',
            'walk_forward_reconcile',
            'chatgpt_auth',
            'chatgpt_usage',
            'chatgpt_reconcile',
        ),
        (
            '示範資料建立',
            '資料匯入',
            '公開資料下載',
            '官方行情更新',
            '回測',
            '策略研究',
            '結果比較',
            '策略啟用',
            '策略停用',
            '帳戶讀取',
            '帳戶對帳',
            '緊急停止',
            '歷史重播',
            '紙上委託',
            '委託取消',
            '備份建立',
            '備份還原',
            '分析預覽',
            'AI 解讀',
            '分析讀取',
            '分析紀錄核對',
            'Walk-forward 預覽',
            'Walk-forward 執行',
            'Walk-forward 讀取',
            'Walk-forward 核對',
            '訂閱連線',
            '訂閱用量讀取',
            '訂閱紀錄核對',
        ),
    )
)


def stop_presentation(account, reason=None, *, manual_lock_text='manual_order_lock'):
    """Keep legacy output; the UI supplies catalogue text for the manual stop."""
    if account.get('manual_order_lock', False):
        return manual_lock_text, '#f1b65c'
    orders = list(account.get('orders', {}).values())
    risk_rejected = bool(orders and orders[-1].get('status') == 'rejected' and orders[-1].get('reason') not in (None, 'kill_switch', 'reconciliation_required'))
    if account.get('consecutive_loss_halt') or account.get('quarantined'):
        return '風控觸發停止；請核對帳戶', '#f1b65c'
    if account.get('kill_switch'):
        if reason == 'user':
            return '緊急停止（使用者觸發）', '#ff8282'
        if risk_rejected:
            return '風控觸發停止；最後委託遭拒', '#f1b65c'
        if account.get('reconciliation_required'):
            return '風控／安全停止；需要對帳', '#f1b65c'
        if reason == 'replay':
            return '重播批次已結束（正常）；新委託仍停止', '#82c9ae'
        return '新委託已停止；原因待核對', '#f1b65c'
    if account.get('reconciliation_required'):
        return '需要對帳；禁止新委託', '#f1b65c'
    if account.get('kill_switch') is not False:
        return '停止狀態未知；請核對帳戶', '#f1b65c'
    return '未停止；仍須通過每次風控與對帳', '#a9c8ee'


def completion_summary(operation, result):
    op = (operation or '').removeprefix('ui_')
    label = OPERATION_LABELS.get(op, '本機作業')
    account = result.get('account', {})
    if op.startswith('paper_'):
        counts = f"部位 {len(account.get('positions', {}))} 項、委託 {len(account.get('orders', {}))} 筆、成交 {len(account.get('fills', {}))} 筆"
        detail = f"帳戶 {account.get('account_id') or '尚未初始化'}，現金 {account.get('cash', '未知')} TWD，{counts}"
        if op == 'paper_replay':
            replay = result.get('replay', {})
            detail = (
                f"處理 {replay.get('processed_bars', '未知')} 根、新增 {replay.get('new_fills', '未知')} 筆成交（游標 {replay.get('cursor', '未知')}），"
                + detail
            )
        if op == 'paper_reconcile':
            detail += '；' + ('仍需對帳' if account.get('reconciliation_required') else '已完成對帳')
    elif op == 'backtest':
        reports = result.get('reports', [])
        metrics = result.get('metrics', {})
        detail = (
            f"{len(reports)} 份報告，淨損益 {metrics.get('net_pnl', '未提供')} TWD、{metrics.get('trade_count', metrics.get('closed_trades', '未提供'))} 筆交易"
        )
    elif op in ('demo', 'import'):
        detail = f"{result.get('bars', result.get('manifest', {}).get('bar_count', '未知'))} 根（{'合成資料' if op == 'demo' else '已匯入資料'}）"
    elif op == 'select':
        detail = '策略版本 ' + str(result.get('strategy_hash', '已保存'))[:16] + '（僅研究／紙上）'
    elif op == 'disable':
        detail = '啟用版本已停用；紙上新委託停止'
    elif op == 'compare':
        detail = f"{len(result.get('rows', []))} 組結果"
    elif op == 'market_refresh':
        providers = result.get('providers', {})
        failures = sum(bool(x.get('error')) for x in providers.values())
        failure_text = f'，{failures} 個失敗' if failures else ''
        detail = f"{len(providers)} 個來源{failure_text}；{sum(x.get('bars') or 0 for x in providers.values())} 根"
    elif op == 'campaign':
        detail = f"{len(result.get('attempts', []))} 個候選，{len(result.get('selected', []))} 個入選"
    elif op.startswith('walk_forward_'):
        detail = f"已評估 {result.get('summary', {}).get('evaluated_oos_folds', 0)} 折；模型呼叫 0"
    elif op.startswith('analysis_'):
        detail = '識別碼 ' + str(result.get('analysis_id', '未提供'))[:12] + '；建議不自動套用'
    elif op == 'refresh':
        detail = f"{len(result.get('downloads', []))} 份下載紀錄"
    elif op.startswith('backup_'):
        detail = '本機封存處理已結束；請核對保存紀錄'
    elif op.startswith('chatgpt_'):
        detail = f"{len(result.get('receipts', []))} 筆請求紀錄；請核對訂閱狀態"
    else:
        detail = '請核對保存紀錄'
    if result.get('manual_export'):
        return '手動 AI 請求已匯出；程式未連線，請自行決定是否分享。'
    return f'{label}完成：{detail}'
