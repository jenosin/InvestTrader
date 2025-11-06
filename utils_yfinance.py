import yfinance as yf
import pandas as pd
from datetime import datetime

def get_usa_stock_yf(stock_code: str, info_type='history'):
    """
    从 yfinance 抓取指定美股的行情数据
    stock_code: 美股代码，如 'AAPL'
    info_type: 'history' | 'current' 获取历史/实时数据
    """
    stock = yf.Ticker(stock_code)

    # 日线历史数据
    stock_df = stock.history(period="1y")
    stock_df.rename(columns={'Close': 'close', 'Open': 'open', 'High': 'high', 'Low': 'low',
                             'Volume': 'volume'}, inplace=True)

    stock_df.index = pd.to_datetime(stock_df.index).tz_convert(None)

    if info_type == 'history':
        return stock_df

    if info_type == 'current':
        stock_dict = stock.get_info()

        price = stock_dict.get('currentPrice', None)
        price = stock_dict.get('regularMarketPrice', 0) if price is None else price
        low = stock_dict.get('dayLow', None)
        high = stock_dict.get('dayHigh', None)
        volume = stock_dict.get('volume', None)
        open_price = stock_dict.get('regularMarketOpen', None)
        last_price = stock_dict.get('regularMarketPreviousClose', 0)
        forecast_change = price / last_price - 1 if last_price > 0 else 0

        # 用今天日期生成 datetime 索引
        today = pd.to_datetime(datetime.now().date())

        current = pd.DataFrame(
            {'close': [price], 'open': [open_price], 'high': [high], 'low': [low], 'volume': [volume]},index=[today])
        # 将历史和当日数据合并
        df_today = pd.concat([stock_df, current])
        df_today.index.name = 'date'

        return df_today, price, forecast_change

if __name__ == "__main__":
    stock = "^IXIC"
    stock_df = get_usa_stock_yf(stock, 'current')
    print(stock_df.head())
    print(stock_df.tail())