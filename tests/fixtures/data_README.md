# Synthetic data fixtures
All prices, quantities and events in data_synthetic_taifex.csv are invented for
parser tests. They are not market history. Header/padding follows the official
30-day CSV observed on 2026-10-09 from:
https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_2026_10_08.zip
No raw official rows are redistributed. Calendar fixtures in test_data.py are
explicit synthetic scenarios, not an official annual trading calendar.
