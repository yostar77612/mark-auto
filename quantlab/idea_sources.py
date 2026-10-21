"""Fixed fallback sources and blocked domains for strategy idea research.

The blocked-domain lists are adapted from Blave-TW/blave-agent
shell/browser/policy.js (https://github.com/Blave-TW/blave-agent, commit
c148e83e00d23387bc89a95fde4888989e6b31e1), Copyright 2025-2026 吾集科技股份有限公司
(WuChi Technology Company Limited), Apache License 2.0; see
packaging/THIRD_PARTY_NOTICES.md. Modified: rewritten in Python as plain
whole-domain lists; exchange domains are blocked entirely instead of by back-office path, and the
lookalike, advertising and exfiltration heuristics were not carried over.
The fixed source list contains URLs only; site terms still apply when reading.
"""

EXCHANGES = (
    'binance.com',
    'binance.us',
    'bingx.com',
    'okx.com',
    'gate.io',
    'gate.com',
    'bybit.com',
    'bitmart.com',
    'bitfinex.com',
    'kucoin.com',
    'coinbase.com',
    'kraken.com',
    'bitget.com',
    'mexc.com',
    'htx.com',
    'huobi.com',
    'crypto.com',
    'upbit.com',
    'bithumb.com',
    'bitstamp.net',
    'gemini.com',
    'deribit.com',
    'hyperliquid.xyz',
    'bitopro.com',
    'maicoin.com',
    'phemex.com',
    'bitflyer.com',
)
BROKERS = (
    'capital.com.tw',
    'capitalfutures.com.tw',
    'pscnet.com.tw',
    'pfcf.com.tw',
    'pfctrade.com',
    'yuanta.com.tw',
    'yuantafutures.com.tw',
    'sinotrade.com.tw',
    'fubon.com',
    'kgi.com.tw',
    'kgieworld.com.tw',
    'cathaysec.com.tw',
    'masterlink.com.tw',
    'concords.com.tw',
    'tssco.com.tw',
    'jihsun.com.tw',
    'president.com.tw',
    'entrust.com.tw',
    'firstrade.com',
    'interactivebrokers.com',
    'schwab.com',
    'fidelity.com',
    'robinhood.com',
    'webull.com',
    'futuhk.com',
    'moomoo.com',
    'etrade.com',
)
BANKS = (
    'sinopac.com',
    'ctbcbank.com',
    'esunbank.com',
    'esunbank.com.tw',
    'cathaybk.com.tw',
    'taishinbank.com.tw',
    'richart.tw',
    'megabank.com.tw',
    'bot.com.tw',
    'firstbank.com.tw',
    'hncb.com.tw',
    'landbank.com.tw',
    'tcb-bank.com.tw',
    'chb.com.tw',
    'scsb.com.tw',
    'kgibank.com.tw',
    'linebank.com.tw',
    'nextbank.com.tw',
    'rakuten-bank.com.tw',
    'citibank.com.tw',
    'hsbc.com.tw',
    'dbs.com.tw',
    'standardchartered.com.tw',
    'ipost.post.gov.tw',
    'feib.com.tw',
    'ubot.com.tw',
    'chase.com',
    'bankofamerica.com',
    'wellsfargo.com',
    'citi.com',
    'hsbc.com',
    'revolut.com',
    'wise.com',
)
PAYMENTS = (
    'paypal.com',
    'ecpay.com.tw',
    'newebpay.com',
    'jkopay.com',
    'tappaysdk.com',
    'pay.line.me',
    'checkout.stripe.com',
    'billing.stripe.com',
    'buy.stripe.com',
    'pay.google.com',
    'payments.google.com',
    'checkout.shopify.com',
    'pay.amazon.com',
)
# The fetch policy blocks every listed domain and its subdomains.
BLOCKED_DOMAINS = tuple(dict.fromkeys(EXCHANGES + BROKERS + BANKS + PAYMENTS))
# OpenAI web_search accepts at most 100 blocked domains, without a scheme.
SEARCH_BLOCKED_DOMAINS = BLOCKED_DOMAINS[:100]

# Fallback when the plan or model cannot use web search. Public index pages only.
FIXED_SOURCES = (
    {'url': 'https://quantpedia.com/blog/', 'label': 'Quantpedia blog'},
    {'url': 'https://quantocracy.com/', 'label': 'Quantocracy'},
    {'url': 'https://www.mql5.com/en/articles', 'label': 'MQL5 articles'},
    {'url': 'https://blog.quantinsti.com/', 'label': 'QuantInsti blog'},
    {'url': 'https://robotwealth.com/blog/', 'label': 'Robot Wealth blog'},
    {'url': 'https://www.xq.com.tw/xstrader/', 'label': 'XQ XS Trader'},
    {'url': 'https://arxiv.org/list/q-fin.TR/recent', 'label': 'arXiv q-fin.TR'},
    {'url': 'https://github.com/je-suis-tm/quant-trading', 'label': 'quant-trading (GitHub)'},
)
