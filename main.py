import sys
import backtrader as bt
import trader
import pandas as pd
from utils_efinance import get_fund_history_ef, get_realtime_rate
from ta_analysis import stock_ta_analysis
import efinance as ef
from openpyxl import load_workbook
import traceback

def backtest_funds(file_path, sheet_name):
    # 打开 workbook
    wb = load_workbook(file_path)
    ws = wb[sheet_name]

    sheet = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl", header=1, dtype={"基金代码": str})
    sheet["操作建议"] = sheet["操作建议"].astype(str)
    sheet["追踪ETF/指数"] = sheet["追踪ETF/指数"].astype(str)

    for index, row in sheet.iterrows():
        code = str(row["基金代码"]).strip()
        if not code or code == "nan":
            continue

        try:
            fund_info = ef.fund.get_base_info(code)
            fund_name = fund_info.get("基金简称", None)
            ws.cell(row=index + 3, column=2, value=fund_name)
            print(f"✅ {code}: {fund_name}")
        except Exception as e:
            print(f"⚠️ 获取 {code} 基金信息失败: {e}")

        df = get_fund_history_ef(code, 1000)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index("date", inplace=True)

        from trader import ceboro_trend
        ceboro_trend(df, trader.OptimizedTaStrategy, False)

        print('-----------------------------------------')

    # 保存 Excel
    wb.save(file_path)

def suggest_funds(file_path, sheet_name):
    # 打开 workbook
    wb = load_workbook(file_path)
    ws = wb[sheet_name]

    sheet = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl", header=1, dtype={"基金代码": str})
    sheet["操作建议"] = sheet["操作建议"].astype(str)
    sheet["追踪ETF/指数"] = sheet["追踪ETF/指数"].astype(str)

    for index, row in sheet.iterrows():
        code = str(row["基金代码"]).strip()
        if not code or code == "nan":
            continue

        etf_code = row["追踪ETF/指数"] if not pd.isna(row["追踪ETF/指数"]) else ""

        try:
            fund_info = ef.fund.get_base_info(code)
            fund_name = fund_info.get("基金简称", None)
            ws.cell(row=index + 3, column=2, value=fund_name)
            print(f"✅ {code}: {fund_name}")
        except Exception as e:
            print(f"⚠️ 获取 {code} 基金信息失败: {e}")

        if not etf_code:
            try:
                fund_position = ef.fund.get_invest_position(code)
                etf_code = fund_position.iloc[0].get("股票代码", None)
                ws.cell(row=index + 3, column=3, value=etf_code)
            except Exception as e:
                print(f"⚠️ 获取 {code} 基金持仓信息失败: {e}")

        fund_rate, etf_name = get_realtime_rate(code, etf_code)
        ws.cell(row=index + 3, column=4, value=f'{etf_name}')
        estimate = fund_rate or 0.0
        ws.cell(row=index + 3, column=5, value=f'{estimate/100:.2%}')

        df = get_fund_history_ef(code, 100)

        from trader import combine_today_info, ceboro_suggestion
        df, forecast_nav = combine_today_info(df, estimate/100)
        action = ceboro_suggestion(df, trader.OptimizedTaStrategy, 'suggestion', forecast_nav, estimate / 100)
        ws.cell(row=index + 3, column=8, value=action)

    # 保存 Excel
    wb.save(file_path)

def backtest_index(index_code):
    from utils_yfinance import get_usa_stock_yf
    df = get_usa_stock_yf(index_code, 'current')

    from trader import ceboro_trend
    ceboro_trend(df, trader.OptimizedTaStrategy, True)

def suggest_index(index_code):
    from utils_yfinance import get_usa_stock_yf
    from trader import ceboro_suggestion
    df, price, estimate = get_usa_stock_yf(index_code, 'current')
    ceboro_suggestion(df, trader.OptimizedTaStrategy, price, estimate)

# ----------------- 获取历史数据和当日预估，获得操作建议 -----------------
if __name__ == "__main__":

    # use = 'funds' | 'stock' | 'backtest_fund' | 'backtest_index' | 'index'
    use = 'backtest_index'
    fund_code = "005918"
    index_code = "^IXIC"
    file_path = "FundEstimate.xlsx"
    sheet_name = "基金操作"

    if use == 'backtest_fund':
        from trader import start_trading
        start_trading(fund_code, trader.OptimizedTaStrategy)
    elif use == 'backtest_funds':
        file_path = "FundEstimate.xlsx"
        backtest_funds(file_path, sheet_name)
    elif use == 'funds':
        suggest_funds(file_path, sheet_name)
    elif use == 'backtest_index':
        backtest_index(index_code)