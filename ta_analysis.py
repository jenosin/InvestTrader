import pandas as pd
import ta
from utils_efinance import get_stock_history_ef, get_fund_history_ef

def calculate_indicators(df):
    """
    计算常用量化指标
    """
    # 移动平均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()

    # EMA
    df['ema5'] = ta.trend.ema_indicator(close=df['close'], window=5)
    df['ema20'] = ta.trend.ema_indicator(close=df['close'], window=20)

    # MACD
    macd = ta.trend.MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_hist'] = macd.macd_diff()

    # 布林带
    from ta.volatility import BollingerBands
    bb = BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_middle'] = bb.bollinger_mavg()
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()

    # KDJ
    from ta.momentum import StochasticOscillator
    stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
    df['k'] = stoch.stoch()
    df['d'] = stoch.stoch_signal()
    df['j'] = 3 * df['k'] - 2 * df['d']

    # RSI
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()

    # ATR（平均真实波幅，用于风险控制）
    df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'],
                                               window=14).average_true_range()

    return df

def generate_trend_scores(df):
    # 趋势指标
    df['trend_up'] = df['ema5'] > df['ema20']
    df['trend_down'] = df['ema5'] < df['ema20']
    df['momentum'] = (df['macd'] > df['macd_signal']) & (df['macd_hist'] > 0)
    df['rsi_ok'] = (df['rsi'] > 40) & (df['rsi'] < 60)
    df['rsi_over'] = df['rsi'] > 70
    df['boll_buy'] = (df['close'] < df['bb_middle']) & (df['close'] > df['bb_lower'])
    df['boll_sell'] = (df['close'] > df['bb_upper']) | (df['close'] < df['bb_middle'])
    df['kdj_buy'] = (df['k'] > df['d']) & (df['j'] < 20)
    df['kdj_sell'] = (df['k'] < df['d']) & (df['j'] > 80)

    # 买入
    weights = {'trend_up': 0.3, 'momentum': 0.25, 'rsi_ok': 0.15, 'boll_buy': 0.15, 'kdj_buy': 0.15}
    df['buy_score'] = (
            df['trend_up'] * weights['trend_up'] +
            df['momentum'] * weights['momentum'] +
            df['rsi_ok'] * weights['rsi_ok'] +
            df['boll_buy'] * weights['boll_buy'] +
            df['kdj_buy'] * weights['kdj_buy']
    )

    # 卖出
    weights_sell = {'trend_down': 0.3, 'momentum_down': 0.25, 'rsi_over': 0.15, 'boll_sell': 0.15, 'kdj_sell': 0.15}
    df['sell_score'] = (
            df['trend_down'] * weights_sell['trend_down'] +
            (df['macd'] < df['macd_signal']) * weights_sell['momentum_down'] +
            df['rsi_over'] * weights_sell['rsi_over'] +
            df['boll_sell'] * weights_sell['boll_sell'] +
            df['kdj_sell'] * weights_sell['kdj_sell']
    )

    df['buy_signal_trend'] = df['buy_score'] >= 0.7
    df['sell_signal_trend'] = df['sell_score'] >= 0.5

    return df

def identify_oscillating(df, atr_threshold=0.02, ma_threshold=0.01):
    """
    判断是否横盘震荡
    """
    df['atr_ratio'] = df['atr'] / df['close']
    df['trend_strength'] = abs(df['ma5'] - df['ma20']) / df['close']
    df['is_oscillating'] = (df['atr_ratio'] < atr_threshold) & (df['trend_strength'] < ma_threshold)

    # 横盘区间
    df['range_top'] = df['bb_upper'] * 0.98
    df['range_bottom'] = df['bb_middle'] * 0.98
    return df

def apply_combined_strategy(df):
    """
    综合趋势+震荡策略
    """
    df['operation'] = '无'

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        today = df.iloc[i]

        # ---------- 冷却期 / 创新低过滤 ----------
        recent_lows = [df.iloc[j]['low'] for j in range(i - 3, i)]
        no_new_low = all(today['low'] >= l for l in recent_lows)

        # 趋势策略买入
        if prev['trend_up'] and today['buy_score'] >= 0.5:
            if today['buy_score'] >= 0.7:
                df.at[i, 'operation'] = '上升趋势，买入 400'
            else:
                df.at[i, 'operation'] = '上升趋势，买入 200'

        # 震荡策略低吸买入
        elif today['is_oscillating']:
            if today['low'] <= today['range_bottom'] and today['rsi'] < 50 and today['close'] > today['ma20'] and no_new_low:
                df.at[i, 'operation'] = '高位震荡，逢低吸纳 200'
            elif today['high'] >= today['range_top'] and today['rsi'] > 70:
                df.at[i, 'operation'] = '高位震荡，获利卖出 10%'

        # 趋势策略卖出
        elif today['sell_signal_trend']:
            df.at[i, 'operation'] = '下降趋势，卖出 20%'

    return df

def save_signals(df, output_path):
    """
    保存带买入信号的结果到 Excel
    """
    df.to_excel(output_path, index=False)

def stock_trade_analysis(code, forecast_change=None, beg='20250101'):
    stock_df = get_stock_history_ef(code, beg)
    df = stock_df if len(stock_df) > 10 else get_fund_history_ef(code, 300)
    df['date'] = pd.to_datetime(df['date'])

    forecast_nav = 0.0
    if forecast_change:
        last_nav = df['close'].iloc[-1]
        forecast_nav = last_nav * (1 + forecast_change)
        forecast_date = df['date'].iloc[-1] + pd.Timedelta(days=1)

        new_row = pd.DataFrame(
            {'date': [forecast_date], 'close': [forecast_nav], 'open': [forecast_nav], 'high': [forecast_nav],
             'low': [forecast_nav]})
        df = pd.concat([df, new_row], ignore_index=True)

    df = calculate_indicators(df)
    df = generate_trend_scores(df)
    df = identify_oscillating(df)
    df = apply_combined_strategy(df)
    # df = generate_signals(df)

    output_excel = f"signals/{code}_signals.xlsx"
    save_signals(df, output_excel)

    signal = df.iloc[-1]['operation']

    forecast_change = forecast_change if forecast_change else 0.0
    print(f"📊 预测净值: {forecast_nav:.4f} ({forecast_change:+.2%})")
    print(f"📈 今日操作建议: {signal or '无'}")
    return signal or '无'

if __name__ == "__main__":
    code = '017437'
    stock_trade_analysis(code)