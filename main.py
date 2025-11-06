import sys
import backtrader as bt
import trader
import pandas as pd
from utils_efinance import get_fund_history_ef, get_realtime_rate
from ta_analysis import stock_trade_analysis
import efinance as ef
from openpyxl import load_workbook
import traceback

# ----------------- 获取历史数据和当日预估，获得操作建议 -----------------
if __name__ == "__main__":

    # use = 'fund' | 'stock' | 'backtest_fund'
    use = 'fund'

    file_path = "FundEstimate.xlsx"
    sheet_name = "基金操作"

    sheet = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl", header=1, dtype={"基金代码": str})
    code_dict = {}
    sheet["操作建议"] = sheet["操作建议"].astype(str)
    sheet["追踪ETF/指数"] = sheet["追踪ETF/指数"].astype(str)

    # 打开 workbook
    wb = load_workbook(file_path)
    ws = wb[sheet_name]

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

        if use == 'fund':
            df = get_fund_history_ef(code, 100)

            from trader import get_today_action
            action = get_today_action(df, estimate/100, trader.OptimizedTaStrategy)
            ws.cell(row=index + 3, column=8, value=action)
        elif use == 'stock':
            action = stock_trade_analysis(code, estimate/100)
            ws.cell(row=index + 3, column=8, value=action)
        elif use == 'backtest_fund':
            df = get_fund_history_ef(code, 1000)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index("date", inplace=True)
            data = bt.feeds.PandasData(dataname=df)

            try:
                cerebro = bt.Cerebro()
                cerebro.adddata(data)
                cerebro.addstrategy(trader.OptimizedTaStrategy,function="trend", full_log=False)
                cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, annualize=True,
                                    riskfreerate=0.02)
                cerebro.broker.setcash(5000.0)
                result = cerebro.run()
                # cerebro.plot()
                sharpe = result[0].analyzers.sharpe.get_analysis()
                print(f"夏普比率: {sharpe.get('sharperatio', 0):.2f}")
            except Exception as e:
                print(f"⚠️ 回测 {code} 基金失败: {e}")
                traceback.print_exc()

        print('-----------------------------------------')

        # sys.exit()

    # 保存 Excel
    wb.save(file_path)