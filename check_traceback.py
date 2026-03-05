import sys, re

with open('d:/Documents/zhihaol/100_Project/2601_Trading/artifacts/runs/dashboard_backtest_us_967ab354977b4befaefd0a52cfc446e6.log', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

text = re.sub(r'backtest loop:\s*\d+%\|.*?\| \d+/\d+ \[.*?\]\r?', '', text)
text = re.sub(r'\s*\[\d+\]\s+train.*?\n', '', text)
text = re.sub(r'\s*\[\d+\]\s+valid.*?\n', '', text)

idx = text.rfind('Traceback (most recent call last)')
if idx != -1:
    print(text[idx:idx+2000])
else:
    print("Traceback not found after cleaning.")
