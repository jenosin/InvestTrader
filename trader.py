import backtrader as bt
import numpy as np
from fontTools.varLib.featureVars import overlayBox


class DynamicAddReduceStrategy(bt.Strategy):
    """
    动态加减仓策略
    基金净值上涨超过5%进入加仓阶段，每天加仓200元
    基金净值下跌超过5%进入减仓阶段，每天减仓10%仓位市值（仅当日净值下跌时减仓）
    记录累计投入资金与持仓成本，计算策略净收益率与超额收益
    适用于基金等波动较小的标的
    """
    params = dict(
        add_threshold=0.05,      # +5% 进入加仓
        reduce_threshold=-0.05,  # -5% 进入减仓
        daily_min_amount=200.0,  # 加仓阶段每天最少加 200 元
        daily_max_amount=500.0,  # 加仓阶段每天最多加 500 元
        reduce_fraction=0.10,    # 减仓阶段每天减 10% 仓位市值
        initial_cash=0.0          # 初始投入现金（用于现金记录）
    )

    def __init__(self):
        self.nav = self.datas[0].close
        self.state = 'INIT'
        self.entry_price = 0
        self.last_nav = 0
        self.start_value = 0
        self.start_nav = 0
        self.recent_high = None
        self.recent_low = None
        self.total_invested = 0.0
        self.hold_shares = 0.0
        self.hold_cost = 0.0
        # 均线
        self.sma_short = bt.ind.SMA(self.datas[0], period=5)
        self.sma_long = bt.ind.SMA(self.datas[0], period=20)
        # 高低点
        self.highest = bt.ind.Highest(self.datas[0].close, period=10)
        self.lowest = bt.ind.Lowest(self.datas[0].close, period=10)

    def next(self):
        nav = self.nav[0]
        date = self.datas[0].datetime.date(0)

        # 高低点趋势
        if nav >= self.highest[-1] and nav > self.lowest[-1]:
            hl_trend = 'up'
        elif nav <= self.lowest[-1] and nav < self.highest[-1]:
            hl_trend = 'down'
        else:
            hl_trend = 'sideways'

        # 均线趋势
        if self.sma_short[0] > self.sma_long[0]:
            ma_trend = 'up'
        elif self.sma_short[0] < self.sma_long[0]:
            ma_trend = 'down'
        else:
            ma_trend = 'sideways'

        # 综合判断：高低点优先
        if hl_trend != 'sideways':
            trend = hl_trend
        else:
            trend = ma_trend

        # 初始建仓
        if self.state == 'INIT':
            amount = min(2000.0, self.broker.getcash())
            size = amount / nav
            self.buy(size=size)
            self.start_value = self.broker.getvalue()
            self.total_invested += amount
            self.last_nav = nav
            self.start_nav = nav
            self.state = 'HOLD'
            self.recent_high = nav
            self.recent_low = nav
            self.log(f"{date} 初始建仓 {size:.2f} 份 @ {nav:.4f}")
            return

        # 先计算累计涨跌幅（相对于当前极值）
        acc_rise = nav / self.recent_low - 1.0  if nav > self.recent_low else 0.0 # 相对于低点的涨幅
        acc_drop = nav / self.recent_high - 1.0 if nav < self.recent_high else 0.0 # 相对于高点的跌幅

        # 状态切换
        if self.state == 'HOLD' or self.state == 'REDUCE':
            if trend == 'up':  #acc_rise >= self.p.add_threshold
                self.state = 'ADD'
            elif trend == 'sideways':
                self.state = 'HOLD'
        elif self.state == 'HOLD' or self.state == 'ADD':
            if trend == 'down':  #acc_drop <= self.p.reduce_threshold or
                self.state = 'REDUCE'
            elif trend == 'sideways':
                self.state = 'HOLD'
        elif trend == 'sideways':
            self.state = 'HOLD'

        if self.state == 'ADD':
            # 加仓阶段每天加仓200元
            cash_available = self.broker.getcash()
            add_size = 0.03 * self.getposition().size
            size_amount = add_size * nav
            max_amount = max(self.p.daily_min_amount, size_amount)
            amount = min(max_amount, cash_available, self.p.daily_max_amount)
            if amount > 0:
                size = amount / nav
                self.buy(size=size)
                self.total_invested += amount
                self.recent_low = nav
                self.log(f"{date} 当日：{nav:.4f}，累计涨幅: {acc_rise:.2%}，累计跌幅: {acc_drop:.2%}, 趋势: {trend}，状态: {self.state}")
                self.log(f"{date} 加仓 {size:.2f} 份 @ {nav:.4f}")
                self.hold_shares += size
                self.hold_cost += size * nav

        elif self.state == 'REDUCE':
            # 减仓阶段，如果基金下跌（今日 NAV < 昨日 NAV）则减仓
            if nav < self.last_nav:
                position_size = self.getposition().size
                size_to_sell = position_size * self.p.reduce_fraction
                if size_to_sell > 0:
                    self.sell(size=size_to_sell)
                    self.recent_high = nav
                    self.log(f"{date} 当日：{nav:.4f}，累计涨幅: {acc_rise:.2%}，累计跌幅: {acc_drop:.2%}, 趋势: {trend}，状态: {self.state}")
                    self.log(f"{date} 减仓 {size_to_sell:.2f} 份 @ {nav:.4f}")
                    if self.hold_shares > 0:
                        avg_cost = self.hold_cost / self.hold_shares
                    else:
                        avg_cost = 0.0
                    # 立即更新成本与持股（按平均成本减少）
                    self.hold_shares -= size_to_sell
                    self.hold_cost -= size_to_sell * avg_cost

        # 更新极值
        self.recent_high = max(self.recent_high, nav)
        self.recent_low = min(self.recent_low, nav)

        # 更新 last_nav
        self.last_nav = nav

    def log(self, txt):
        print(txt)
        # pass

    def stop(self):
        # 最终统计
        pos = self.getposition()
        final_value = pos.size * self.nav[0]

        if self.hold_shares > 0:
            hold_value = self.hold_shares * self.nav[0]
            roi = (hold_value - self.hold_cost) / self.hold_cost
        else:
            roi = None

        end_nav = self.datas[0].close[0]
        fund_return = end_nav / self.start_nav - 1

        print(f"最终仓位: {pos.size:.2f} 份")
        print(f"期末现金: {self.broker.getcash():.2f} 元")
        print(f"组合市值: {final_value:.2f} 元")

        print(f"基金涨跌幅: {fund_return:.2%}")
        print(f"累计投入资金: {self.total_invested:.2f}")
        print(f"最终持仓市值: {final_value:.2f}")
        print(f"策略净收益率（仅仓位）: {roi:.2%}")
        print(f"超额收益: {roi - fund_return:.2%}")

import backtrader as bt
import pandas as pd
import traceback

class DailyTrendSwingStrategy(bt.Strategy):
    params = dict(
        initial_amount=2000.0,  # 初始建仓金额（元）
        ma_short=5,           # MA5
        ma_mid=20,            # MA20
        ma_long=60,           # MA60
        boll_period=20,       # 布林带用的周期
        daily_amount=200.0,  # 每日基准投金额（元）
        add_on_pullback_ratio=1.5,  # 上升趋势回踩 MA20 时追加比例 = daily_amount * ratio
        sell_fraction_on_high=0.10, # 高位卖出每次卖出仓位比例
        reduce_step=0.20,     # 下跌趋势每次减仓比例(例如 0.2 -> 20%)
        bottom_ratio=0.10,    # 在下跌过程中保留历史最大持仓的 10% 为底仓
        sell_on_high_pct=0.05,# 高位突破上轨或日内涨幅超过 5% 卖出触发阈值
        osc_band_tol=0.02,    # 用于判定均线“纠缠”的容差（2%）
        min_cash_buffer=0.0,   # 保留最小现金缓冲（元）
        function='suggestion', # 'trend' 用于回测，'suggestion' 用于生成建议
    )

    def __init__(self):
        # 指标
        self.close = self.datas[0].close
        self.ma_short = bt.ind.SMA(self.datas[0], period=self.p.ma_short)
        self.ma_mid = bt.ind.SMA(self.datas[0], period=self.p.ma_mid)
        self.ma_long = bt.ind.SMA(self.datas[0], period=self.p.ma_long)
        self.bbands = bt.ind.BollingerBands(self.datas[0], period=self.p.boll_period)
        self.signal = None

        # 持仓成本与份额（用 notify_order 更新）
        self.hold_shares = 0.0
        self.hold_cost = 0.0     # 当前持仓对应的总成本（只包含尚未卖出的那部分）
        self.realized_pnl = 0.0

        # 记录历史最大持仓，用于 bottom_ratio 计算
        self.max_hold_shares = 0.0

        # 用于下单追踪
        self.order = None

        # 日志/调试
        self.start_nav = None
        self.start_value = None

    # --------- 帮助函数 ----------
    def log(self, txt):
        if self.p.function == 'single_trend':
            print(txt)

    def _is_up_trend(self):
        # 严格顺序：MA5 > MA20 > MA60 且 价格 > MA5
        return (self.ma_short[0] > self.ma_mid[0] > self.ma_long[0]) and (self.close[0] > self.ma_short[0])

    def _is_down_trend(self):
        # 严格空头排列：MA5 < MA20 < MA60 且 价格 < MA20
        return (self.ma_short[0] < self.ma_mid[0] < self.ma_long[0]) and (self.close[0] < self.ma_mid[0])

    def _is_high_osc(self):
        # 价格高于 MA60，且 MA5 与 MA20 在相对较小带宽内（纠缠） -> 高位震荡
        if self.close[0] <= self.ma_long[0]:
            return False
        denom = self.ma_mid[0] if self.ma_mid[0] != 0 else 1
        return abs(self.ma_short[0] - self.ma_mid[0]) / denom <= self.p.osc_band_tol

    def _is_low_osc(self):
        # 价格低于 MA60，且均线收敛（低位震荡）
        if self.close[0] >= self.ma_long[0]:
            return False
        denom = self.ma_mid[0] if self.ma_mid[0] != 0 else 1
        return abs(self.ma_short[0] - self.ma_mid[0]) / denom <= self.p.osc_band_tol

    def _cash_available(self):
        return self.broker.getcash() - self.p.min_cash_buffer

    # --------- 订单回报（使用实际成交价/数量更新成本） ----------
    def notify_order(self, order):
        # 仅在订单完成时处理
        if order.status in [order.Submitted, order.Accepted]:
            return

        dt = self.datas[0].datetime.date(0)
        if order.status == order.Completed:
            ex_size = order.executed.size
            ex_price = order.executed.price
            if order.isbuy():
                # 成交买入：增加持仓份额和持仓成本
                self.hold_shares += ex_size
                self.hold_cost += ex_size * ex_price
                self.realized_pnl += 0.0  # 未实现不计入
                # 更新历史最高持仓
                if self.hold_shares > self.max_hold_shares:
                    self.max_hold_shares = self.hold_shares
                self.log(f"{dt} BUY 成交: qty={ex_size:.4f} @ {ex_price:.4f} | hold_shares={self.hold_shares:.4f}, hold_cost={self.hold_cost:.2f}")
            elif order.issell():
                # 成交卖出：按平均成本减少持仓成本，记录已实现盈亏
                avg_cost = (self.hold_cost / self.hold_shares) if self.hold_shares > 0 else 0.0
                # ex_size is positive for executed size
                realized = ex_size * (ex_price - avg_cost)
                self.realized_pnl += realized
                # 减少持仓份额 & 成本（按 avg_cost）
                self.hold_shares -= ex_size
                self.hold_cost -= ex_size * avg_cost
                # numeric safety
                if self.hold_shares < 1e-12:
                    self.hold_shares = 0.0
                    self.hold_cost = 0.0
                self.log(f"{dt} SELL 成交: qty={ex_size:.4f} @ {ex_price:.4f} | realized={realized:.2f}, hold_shares={self.hold_shares:.4f}, hold_cost={self.hold_cost:.2f}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order Canceled/Margin/Rejected status={order.status}")
        self.order = None

    # --------- 策略主逻辑 ----------
    def next(self):
        nav = float(self.close[0])
        date = self.datas[0].datetime.date(0)

        # 初始建仓（第一次有机会买时）
        if self.start_nav is None and self.p.function == 'trend':
            # 采用首日按 daily_amount 建仓（如果有资金）
            amt = min(self.p.initial_amount, self._cash_available())
            if amt > 0:
                size = amt / nav
                self.order = self.buy(size=size)
                # start_nav / start_value 等在 notify_order 中记录成交价更准确
            self.start_nav = nav
            self.start_value = self.broker.getvalue()
            # 打印首日信息
            self.log(f"{date} 开始：NAV={nav:.4f}, 计划初始投 {amt:.2f}")
            return

        # 指标值
        ma5 = float(self.ma_short[0])
        ma20 = float(self.ma_mid[0])
        ma60 = float(self.ma_long[0])
        bb_mid = float(self.bbands.lines.mid[0])
        bb_top = float(self.bbands.lines.top[0])
        bb_bot = float(self.bbands.lines.bot[0])

        # 判定市场状态
        is_up = self._is_up_trend()
        is_down = self._is_down_trend()
        is_high_osc = self._is_high_osc()
        is_low_osc = self._is_low_osc()

        # 计算日内涨幅参考（相对于前一日 close）
        prev_close = float(self.close[-1]) if len(self.data) > 1 else nav
        day_pct = (nav / prev_close - 1.0) if prev_close != 0 else 0.0

        # 打印关键指标（可注释以减少日志）
        self.log(f"{date} 净值：{nav:.4f} | 上升：{is_up} 下跌：{is_down} 高位震荡：{is_high_osc} 低位震荡：{is_low_osc}")

        pos = self.getposition()
        cash_avail = self._cash_available()

        # ---------- 上升趋势 ----------
        if is_up:
            # 每日定投基准
            amt = min(self.p.daily_amount, cash_avail)
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} 上升趋势 每日定投 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"上升趋势，加仓 {self.p.daily_amount:.2f}"

            # 额外低吸：当回踩 MA20 (或回到布林中轨附近) 且有现金
            if nav <= ma20:
                extra = min(self.p.daily_amount * self.p.add_on_pullback_ratio, cash_avail)
                if extra > 0 and cash_avail > 0 and self.p.function == 'trend':
                    size = extra / nav
                    self.buy(size=size)
                    self.log(f"{date} 上升趋势 回踩 MA20 低吸 {extra:.2f} -> {size:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"上升趋势回踩MA20，低吸 {extra:.2f}"

        # ---------- 高位震荡 ----------
        elif is_high_osc:
            # 逢低吸纳：当靠近 MA20 或布林下轨时买入
            if nav <= ma20 or nav <= bb_mid:
                amt = min(self.p.daily_amount, cash_avail)
                if amt > 0 and self.p.function == 'trend':
                    size = amt / nav
                    self.buy(size=size)
                    self.log(f"{date} 高位震荡 逢低吸纳 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"高位震荡，逢低吸纳 {amt:.2f}"

            # 逢高卖出：到布林上轨或日内涨幅超过阈值时卖出一部分
            if nav >= bb_top or day_pct >= self.p.sell_on_high_pct:
                if pos.size > 0 and self.p.function == 'trend':
                    size_to_sell = pos.size * self.p.sell_fraction_on_high
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(f"{date} 高位震荡 逢高卖出 {size_to_sell:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"高位震荡，逢高卖出 {self.p.sell_fraction_on_high:.2%} 仓位"

        # ---------- 低位震荡 ----------
        elif is_low_osc:
            # 低位震荡不操作
            self.log(f"{date} 低位震荡，暂不操作")
            self.signal = "低位震荡，暂不操作"

        # ---------- 下跌趋势 ----------
        elif is_down:
            # 按 reduce_step 分阶段减仓，但不减到低于历史最大持仓的 bottom_ratio
            if pos.size > 0 and self.max_hold_shares > 0 and self.p.function == 'trend':
                min_allowed = self.max_hold_shares * self.p.bottom_ratio
                can_reduce = max(0.0, pos.size - min_allowed)
                if can_reduce > 0:
                    size_to_sell = min(pos.size * self.p.reduce_step, can_reduce)
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(f"{date} 下跌趋势 分阶段减仓 {size_to_sell:.4f} 份 @ {nav:.4f} (保留底仓 {min_allowed:.4f})")
            elif self.p.function == 'suggestion':
                self.signal = f"下跌趋势，分阶段减仓 {self.p.reduce_step:.2%} 仓位"
            else:
                self.log(f"{date} 下跌趋势，但无可减仓位或尚无历史持仓")

        # ---------- 其他情况（保守） ----------
        else:
            # 未匹配到任何明确状态，保守策略：小额定投或不操作
            self.log(f"{date} 未明确信号，保守处理：不操作或小额低吸")
            self.signal = "未明确信号，保守处理"
            # 可启用小额定投（注释掉表示不操作）
            # amt = min(0.2*self.p.daily_amount, cash_avail)
            # if amt > 0:
            #     self.buy(size=amt/nav)
            #     self.log(f"{date} 未明确信号 小额投 {amt:.2f}")

    def stop(self):
        # 计算 final metrics
        nav = float(self.close[0])
        hold_value = self.hold_shares * nav
        unrealized = hold_value - self.hold_cost
        total_realized = self.realized_pnl
        if self.hold_cost > 0:
            hold_roi = (hold_value - self.hold_cost) / self.hold_cost
        else:
            hold_roi = None

        if self.p.function != 'suggestion':
            self.log("\n=== 回测结果 ===")
            self.log(f"最终日期: {self.datas[0].datetime.date(0)}")
            self.log(f"持仓份额: {self.hold_shares:.4f}")
            self.log(f"持仓成本(total): {self.hold_cost:.2f}")
            self.log(f"持仓市值: {hold_value:.2f}")
            self.log(f"未实现 PnL: {unrealized:.2f}")
            self.log(f"已实现 PnL: {total_realized:.2f}")
            if hold_roi is not None:
                self.log(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            else:
                self.log("仅仓位收益率 (hold ROI): N/A (无持仓成本)")
            self.log(f"总资金 (broker): {self.broker.getvalue():.2f}")
            self.log("================\n")

        print(f"持仓市值: {hold_value:.2f}")
        print(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
        print(f"总资金 (broker): {self.broker.getvalue():.2f}")

    def get_signal(self):
        return self.signal

class TaStrategy(bt.Strategy):
    params = dict(
        initial_amount=2000.0,  # 初始建仓金额（元）
        daily_amount=200.0,  # 每日基准投金额（元）
        add_on_pullback_ratio=1.5,  # 上升趋势回踩 MA20 时追加比例 = daily_amount * ratio
        sell_fraction_on_high=0.10, # 高位卖出每次卖出仓位比例
        reduce_step=0.10,     # 下跌趋势每次减仓比例(例如 0.1 -> 10%)
        bottom_ratio=0.10,    # 在下跌过程中保留历史最大持仓的 10% 为底仓
        sell_on_high_pct=0.05,# 高位突破上轨或日内涨幅超过 5% 卖出触发阈值
        osc_band_tol=0.02,    # 用于判定均线“纠缠”的容差（2%）
        min_cash_buffer=0.0,   # 保留最小现金缓冲（元）
        function='suggestion', # 'trend' 用于回测，'suggestion' 用于生成建议
        full_log=False,
    )

    def __init__(self):
        # 基础数据
        self.close = self.datas[0].close
        self.low = self.datas[0].low
        self.high = self.datas[0].high
        self.open = self.datas[0].open

        # 多周期均线系统
        self.ma_short = bt.ind.SMA(self.datas[0], period=5)
        self.ma_mid = bt.ind.SMA(self.datas[0], period=10)
        self.ma_long = bt.ind.SMA(self.datas[0], period=20)

        # EMA系统增强趋势判断
        self.ema_fast = bt.indicators.EMA(self.data.close, period=9)
        self.ema_mid = bt.indicators.EMA(self.data.close, period=21)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=50)

        # 布林带
        self.bbands = bt.ind.BollingerBands(self.datas[0], period=20)

        # MACD
        self.macd = bt.indicators.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)
        self.macd_hist = self.macd.macd - self.macd.signal

        # RSI, ATR, KDJ
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.atr = bt.indicators.ATR(self.data, period=14)
        self.stoch = bt.indicators.Stochastic(self.data, period=14, period_dfast=3, period_dslow=3)
        self.kdj_k = self.stoch.percK
        self.kdj_d = self.stoch.percD
        self.kdj_j = 3 * self.kdj_k - 2 * self.kdj_d

        # 持仓成本与份额（用 notify_order 更新）
        self.hold_shares = 0.0
        self.hold_cost = 0.0     # 当前持仓对应的总成本（只包含尚未卖出的那部分）
        self.realized_pnl = 0.0
        self.max_hold_shares = 0.0

        # 用于下单追踪
        self.order = None
        self.signal = None

        # 状态跟踪
        self.start_nav = None
        self.start_value = None

    # --------- 帮助函数 ----------
    def log(self, txt):
        if self.p.function == 'trend' and self.p.full_log:
            print(txt)

    def _is_up_trend(self):
        # 严格顺序：MA5 > MA10 > MA20 且 价格 > MA5
        return (self.ma_short[0] > self.ma_mid[0] > self.ma_long[0]) and self.close[0] > self.ma_short[0]

    def _is_down_trend(self):
        # 严格空头排列：MA5 < MA10 < MA20 且 价格 < MA20
        return (self.ma_short[0] < self.ma_mid[0] < self.ma_long[0]) and self.close[0] < self.ma_mid[0]

    def _is_momentum(self):
        return self.macd.macd[0] > self.macd.signal[0] and (self.macd.macd[0] - self.macd.signal[0]) > 0

    def _is_rsi_ok(self):
        return 40 < self.rsi[0] < 60

    def _is_rsi_over(self):
        return self.rsi[0] > 70

    def _is_boll_buy(self):
        return self.close[0] < self.bbands.lines.mid[0] and self.close[0] > self.bbands.lines.bot[0]

    def _is_boll_sell(self):
        return self.close[0] > self.bbands.lines.top[0] or self.close[0] < self.bbands.lines.mid[0]

    def _is_kdj_buy(self):
        return self.kdj_k[0] > self.kdj_d[0] and self.kdj_j[0] < 20

    def _is_kdj_sell(self):
        return self.kdj_k[0] < self.kdj_d[0] and self.kdj_j[0] > 80

    def _buy_score(self):
        buy_score = (self._is_up_trend() * 0.5 +
                     self._is_momentum() * 0.25 +
                     self._is_rsi_ok() * 0.15 +
                     self._is_boll_buy() * 0.15 +
                     self._is_kdj_buy() * 0.15
                     )

        return buy_score

    def _buy_score_2(self):
        """
        连续评分版本：
        - 趋势强弱归一化 0~1
        - RSI 越低越好，0~1
        - 动量越强越好，0~1
        - BOLL/KDJ 越接近买入点越高分
        """
        trend_score = max(0, min(1, (self.ema_fast[0] - self.ema_slow[0]) / self.ema_slow[0]))
        momentum_score = max(0, min(1, (self.close[0] - self.close[-5]) / self.close[-5]))
        rsi_score = max(0, min(1, (50 - self.rsi[0]) / 50))
        boll_score = max(0, min(1, (self.bbands.lines.mid[0] - self.low[0]) / (
                    self.bbands.lines.mid[0] - self.bbands.lines.bot[0])))
        kdj_score = max(0, min(1, (50 - self.kdj_k[0]) / 50))

        buy_score = (trend_score * 0.5 +
                     momentum_score * 0.25 +
                     rsi_score * 0.15 +
                     boll_score * 0.15 +
                     kdj_score * 0.15)

        return buy_score

    def _sell_score(self):
        sell_score = (self._is_down_trend() * 0.5 +
                     self._is_momentum() * 0.25 +
                     self._is_rsi_over() * 0.15 +
                     self._is_boll_sell() * 0.15 +
                     self._is_kdj_sell() * 0.15
                     )

        return sell_score

    def _sell_score_2(self):
        """
        连续评分版本：
        - 趋势下降越明显越高
        - RSI 越高越好
        - 动量下降越明显越高
        - BOLL/KDJ 卖出点越高越高分
        """
        trend_down_score = max(0, min(1, (self.ema_slow[0] - self.ema_fast[0]) / self.ema_slow[0]))
        momentum_score = max(0, min(1, (self.close[-5] - self.close[0]) / self.close[-5]))
        rsi_score = max(0, min(1, (self.rsi[0] - 50) / 50))
        boll_score = max(0, min(1, (self.high[0] - self.bbands.lines.mid[0]) / (
                    self.bbands.lines.top[0] - self.bbands.lines.mid[0])))
        kdj_score = max(0, min(1, (self.kdj_k[0] - 50) / 50))

        sell_score = (trend_down_score * 0.5 +
                      momentum_score * 0.25 +
                      rsi_score * 0.15 +
                      boll_score * 0.15 +
                      kdj_score * 0.15)

        return sell_score

    def _is_oscillating(self):
        """
        判断是否横盘震荡
        """
        atr_ratio = self.atr[0] / self.close[0]
        trend_strength = abs(self.ma_short[0] - self.ma_mid[0]) / self.close[0]
        is_oscillating = (atr_ratio < 0.02) & (trend_strength < 0.01)

        return is_oscillating

    def _cash_available(self):
        return self.broker.getcash() - self.p.min_cash_buffer

    # --------- 订单回报（使用实际成交价/数量更新成本） ----------
    def notify_order(self, order):
        # 仅在订单完成时处理
        if order.status in [order.Submitted, order.Accepted]:
            return

        dt = self.datas[0].datetime.date(0)
        if order.status == order.Completed:
            ex_size = order.executed.size  # 买为正，卖为负
            ex_price = order.executed.price

            # 平均成本（只有有持仓时才有效）
            avg_cost = (self.hold_cost / self.hold_shares) if self.hold_shares > 0 else 0.0

            # 更新持仓与成本
            self.hold_shares += ex_size  # 自动增减
            self.hold_cost += ex_size * ex_price  # 买正卖负，自动减少成本

            # 计算已实现盈亏（仅卖出时有效）
            realized = 0.0
            if ex_size < 0:
                realized = -ex_size * (ex_price - avg_cost)
                self.realized_pnl += realized

            # 安全限制
            if self.hold_shares < 1e-12:
                self.hold_shares = 0.0
                self.hold_cost = 0.0

            self.log(f"{dt} {'BUY' if ex_size > 0 else 'SELL'} 成交: qty={ex_size:.4f} @ {ex_price:.4f} "
                     f"| realized={realized:.2f}, hold_shares={self.hold_shares:.4f}, hold_cost={self.hold_cost:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order {order.Status[order.status]}")

        self.order = None

    # --------- 策略主逻辑 ----------
    def next(self):
        nav = float(self.close[0])
        date = self.datas[0].datetime.date(0)

        # 初始建仓（第一次有机会买时）
        if self.start_nav is None and self.p.function == 'trend':
            # 采用首日按 daily_amount 建仓（如果有资金）
            amt = min(self.p.initial_amount, self._cash_available())
            if amt > 0:
                size = amt / nav
                self.order = self.buy(size=size)
                # start_nav / start_value 等在 notify_order 中记录成交价更准确
            self.start_nav = nav
            self.start_value = self.broker.getvalue()
            # 打印首日信息
            self.log(f"{date} 开始：NAV={nav:.4f}, 计划初始投 {amt:.2f}")
            return

        # 计算日内涨幅参考（相对于前一日 close）
        prev_close = float(self.close[-1]) if len(self.data) > 1 else nav
        day_pct = (nav / prev_close - 1.0) if prev_close != 0 else 0.0

        pos = self.getposition()
        cash_avail = self._cash_available()

        range_top = self.bbands.lines.top[0] * 0.98
        range_mid = self.bbands.lines.mid[0]
        range_bottom = self.bbands.lines.mid[0] * 0.98

        # ---------- 趋势判断 ----------
        ema_fast = self.ema_fast[0]
        ema_slow = self.ema_slow[0]
        trend_up = self.ma_short[0] > self.ma_mid[0]
        trend_down = self.ma_short[0] < self.ma_mid[0]

        buy_score = self._buy_score()
        sell_score = self._sell_score()
        rsi_val = self.rsi[0]

        # ---------- 冷却期 / 创新低过滤 ----------
        recent_lows = [self.low[-i] for i in range(1, 4)]
        no_new_low = all(self.low[0] >= l for l in recent_lows)

        self.log(f"buy_score: {buy_score:.3f}, sell_score: {sell_score:.3f}, rsi: {rsi_val:.2f}, trend_up: {trend_up}, trend_down: {trend_down}")

        # ---------- 上升趋势 ----------
        if (trend_up and buy_score >= 0.5 and
                (self.low[0] < range_mid or
                (self.low[0] > range_mid and buy_score >= 0.7) or
                 30 < rsi_val < 60 or
                 self.close[0] > self.close[-1])):
                # 每日定投基准
                buy_amount = self.p.daily_amount * 2 if buy_score >= 0.7 else self.p.daily_amount
                amt = min(buy_amount, cash_avail)
                if amt > 0 and self.p.function == 'trend':
                    size = amt / nav
                    self.buy(size=size)
                    self.log(f"{date} 上升趋势，买入 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"上升趋势，加仓 {buy_amount:.2f}"
                    self.log(self.signal)

        # 额外低吸：上升趋势、震荡回到布林下轨附近或低位且有现金
        elif self._is_oscillating() and self.low[0] < range_bottom and rsi_val < 50:
            extra = min(self.p.daily_amount * self.p.add_on_pullback_ratio, cash_avail)
            if extra > 0 and cash_avail > 0 and self.p.function == 'trend':
                size = extra / nav
                self.buy(size=size)
                self.log(f"{date} 逢低吸纳 {extra:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"逢低吸纳 {extra:.2f}"
                self.log(self.signal)

        # ---------- 高位震荡 ----------
        elif self._is_oscillating() and self.high[0] >= range_top and rsi_val > 70:
            if pos.size > 0 and self.p.function == 'trend':
                size_to_sell = pos.size * self.p.sell_fraction_on_high
                if size_to_sell > 0:
                    self.sell(size=size_to_sell)
                    self.log(f"{date} 高位震荡 逢高卖出 {size_to_sell:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"高位震荡，逢高卖出 {self.p.sell_fraction_on_high:.2%} 仓位"
                self.log(self.signal)

        # ---------- 下跌趋势 ----------
        elif trend_down and sell_score >= 0.5:
            # 按 reduce_step 分阶段减仓，但不减到低于历史最大持仓的 bottom_ratio
            reduce_step = self.p.reduce_step * 2 if sell_score >= 0.7 else self.p.reduce_step
            if pos.size > 0 and self.p.function == 'trend':
                min_allowed = 500
                can_reduce = max(0.0, pos.size - min_allowed)
                if can_reduce > 0:
                    size_to_sell = min(pos.size * reduce_step, can_reduce)
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(f"{date} 下跌趋势 分阶段减仓 {size_to_sell:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"下跌趋势，分阶段减仓 {self.p.reduce_step:.2%} 仓位，最少100份"
                self.log(self.signal)
            else:
                self.log(f"{date} 下跌趋势，但无可减仓位或尚无历史持仓")

        # ---------- 其他情况（保守） ----------
        else:
            # 未匹配到任何明确状态，保守策略：小额定投或不操作
            self.log(f"{date} 未明确信号，保守处理：不操作或小额低吸")
            self.signal = "未明确信号，保守处理"
            # 可启用小额定投（注释掉表示不操作）
            # amt = min(0.2*self.p.daily_amount, cash_avail)
            # if amt > 0:
            #     self.buy(size=amt/nav)
            #     self.log(f"{date} 未明确信号 小额投 {amt:.2f}")

    def stop(self):
        # 计算 final metrics
        nav = float(self.close[0])
        hold_value = self.hold_shares * nav
        unrealized = hold_value - self.hold_cost
        total_realized = self.realized_pnl
        if self.hold_cost > 0:
            hold_roi = (hold_value - self.hold_cost) / self.hold_cost
        else:
            hold_roi = None

        if self.p.function != 'suggestion':
            self.log("\n=== 回测结果 ===")
            self.log(f"最终日期: {self.datas[0].datetime.date(0)}")
            self.log(f"持仓份额: {self.hold_shares:.4f}")
            self.log(f"持仓成本(total): {self.hold_cost:.2f}")
            self.log(f"持仓市值: {hold_value:.2f}")
            self.log(f"未实现 PnL: {unrealized:.2f}")
            self.log(f"已实现 PnL: {total_realized:.2f}")
            if hold_roi is not None:
                self.log(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            else:
                self.log("仅仓位收益率 (hold ROI): N/A (无持仓成本)")
            self.log(f"总资金 (broker): {self.broker.getvalue():.2f}")
            self.log("================\n")

        if not self.p.full_log and 'trend' in self.p.function:
            print(f"持仓市值: {hold_value:.2f}")
            print(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            print(f"总资金 (broker): {self.broker.getvalue():.2f}")

    def get_signal(self):
        return self.signal

class TrendScore(bt.Indicator):
    lines = ('score', 'trend')
    params = dict(
        period_ema_short=5,
        period_ema_mid=20,
        period_ema_long=60,
        period_rsi=14,
        period_momentum=10,
        period_kdj=9,
        period_adx=14,
        period_boll=20,
    )

    def __init__(self):
        # ===== EMA =====
        ema5 = bt.ind.EMA(period=self.p.period_ema_short)
        ema20 = bt.ind.EMA(period=self.p.period_ema_mid)
        ema60 = bt.ind.EMA(period=self.p.period_ema_long)

        self.ema5 = ema5
        self.ema20 = ema20
        self.ema60 = ema60

        # ===== MACD =====
        macd = bt.ind.MACD()
        self.macd = macd.macd
        self.macdsig = macd.signal

        # 金叉死叉（今日>昨日 + MACD与Signal交叉）
        self.macd_cross = bt.ind.CrossOver(self.macd, self.macdsig)

        # ===== KDJ =====
        k = bt.ind.Stochastic(period=self.p.period_kdj)
        self.k = k.percK
        self.d = k.percD
        self.kdj_cross = bt.ind.CrossOver(self.k, self.d)

        # ===== ADX =====
        self.adx = bt.ind.ADX(period=self.p.period_adx)
        self.diplus = bt.ind.PlusDI(period=self.p.period_adx)
        self.diminus = bt.ind.MinusDI(period=self.p.period_adx)

        # ===== Momentum =====
        self.momentum = bt.ind.Momentum(period=self.p.period_momentum)

        # ===== RSI =====
        self.rsi = bt.ind.RSI(period=self.p.period_rsi)

        # ===== Bollinger Bands =====
        self.boll = bt.ind.BollingerBands(period=self.p.period_boll)
        self.upper = self.boll.top
        self.lower = self.boll.bot

    def next(self):
        score = 0

        # ===== EMA评分 =====
        if self.ema5[0] > self.ema20[0] > self.ema60[0]:
            score += 2
        elif self.ema5[0] > self.ema20[0]:
            score += 1
        elif self.ema5[0] < self.ema20[0] < self.ema60[0]:
            score -= 2
        elif self.ema5[0] < self.ema20[0]:
            score -= 1

        # ===== MACD评分 =====
        if self.macd_cross[0] > 0:
            score += 2  # 金叉
        elif self.macd_cross[0] < 0:
            score -= 2  # 死叉

        # ===== KDJ评分 =====
        if self.kdj_cross[0] > 0:
            score += 1
        elif self.kdj_cross[0] < 0:
            score -= 1

        # ===== ADX评分 =====
        if self.adx[0] > 25:
            if self.diplus[0] > self.diminus[0]:
                score += 1
            else:
                score -= 1

        # ===== Momentum =====
        if self.momentum[0] > 0:
            score += 1
        elif self.momentum[0] < 0:
            score -= 1

        # ===== RSI =====
        if self.rsi[0] > 70:
            score -= 1
        elif self.rsi[0] < 30:
            score += 1

        # ===== Bollinger Bands =====
        close = self.data.close[0]
        if close > self.upper[0]:
            score -= 1
        elif close < self.lower[0]:
            score += 1

        # 输出
        self.lines.score[0] = score

        # 分类趋势
        if score >= 6:
            self.lines.trend[0] = 2     # strong_up
        elif score >= 3:
            self.lines.trend[0] = 1     # weak_up
        elif score > -2:
            self.lines.trend[0] = 0     # consolidation
        elif score > -5:
            self.lines.trend[0] = -1    # weak_down
        else:
            self.lines.trend[0] = -2    # strong_down

class ScoredTaStrategy(bt.Strategy):
    """
    使用评分系统的 TaStrategy 策略，改进了趋势判断算法、增强了指标可靠性并优化了加减仓逻辑
    """
    params = dict(
        initial_amount=1000.0,  # 初始建仓金额（元）
        daily_amount=200.0,  # 每日基准投金额（元）
        add_on_pullback_ratio=1.5,  # 上升趋势回踩追加比例
        sell_fraction_on_high=0.10,  # 高位卖出仓位比例
        reduce_step=0.10,  # 下跌趋势每次减仓比例
        bottom_ratio=0.10,  # 保留历史最大持仓比例
        sell_on_high_pct=0.05,  # 高位卖出触发阈值
        osc_band_tol=0.02,  # 均线"纠缠"容差
        min_cash_buffer=0.0,  # 保留最小现金缓冲
        function='suggestion',  # 'trend' 用于回测，'suggestion' 用于生成建议
        full_log=False,
    )

    def __init__(self):
        # 趋势评分
        self.score = TrendScore()

        # 基础数据
        self.close = self.datas[0].close
        self.low = self.datas[0].low
        self.high = self.datas[0].high
        self.open = self.datas[0].open
        self.volume = self.datas[0].volume
        self.vol_ratio = 0.0

        # EMA系统增强趋势判断
        self.ema20 = bt.indicators.EMA(self.data.close, period=21)

        # 布林带
        self.boll = bt.ind.BollingerBands(self.datas[0], period=20)

        # 动量指标
        self.momentum = bt.indicators.Momentum(self.data.close, period=10)

        # RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

        # 成交量相关指标
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)  # 成交量20日均线

        self.signal = None
        self.indicators = None

        # 持仓管理
        self.hold_shares = 0.0
        self.hold_cost = 0.0
        self.realized_pnl = 0.0
        self.max_hold_shares = 0.0

        # 订单跟踪
        self.order = None

        # 状态跟踪
        self.start_nav = None
        self.start_value = None
        self.consecutive_up_days = 0  # 连续上涨天数
        self.consecutive_down_days = 0  # 连续下跌天数

    def log(self, txt):
        if self.p.function == 'trend' and self.p.full_log and len(self) > 250:
            print(txt)

    def _is_volume_breakout(self):
        """
        判断是否有放量突破
        """
        # 成交量是近期平均的2倍以上
        high_volume = self.vol_ratio > 2.0

        # 同时价格上涨
        price_increase = self.close[0] > self.close[-1]

        return high_volume and price_increase

    def _is_volume_shrink(self):
        """
        判断是否缩量
        """
        # 成交量低于平均值的50%
        low_volume = 0.0 < self.vol_ratio < 0.5
        return low_volume

    def _is_bullish_volume_divergence(self):
        """
        判断是否存在看涨的量价背离
        价格创新低但成交量放大
        """
        # 价格创近期新低
        recent_low_price = min([self.close[-i] for i in range(1, 6)])
        price_new_low = self.close[0] < recent_low_price

        # 但成交量放大
        volume_increase = self.vol_ratio > 1.5

        return price_new_low and volume_increase

    def _is_bearish_volume_divergence(self):
        """
        判断是否存在看跌的量价背离
        价格创新高但成交量萎缩
        """
        # 价格创近期新高
        recent_high_price = max([self.close[-i] for i in range(1, 6)])
        price_new_high = self.close[0] > recent_high_price

        # 但成交量萎缩
        volume_shrink = 0.0 < self.vol_ratio < 0.7

        return price_new_high and volume_shrink

    def _is_good_entry_point(self):
        """
            判断是否为良好的建仓时机
            """
        up_score = self.score.score[0] > 0

        # 条件4: 成交量放大（有资金流入迹象）
        volume_support = self.vol_ratio > 1.0

        # 综合判断
        return up_score and volume_support

    def _calculate_position_size(self, target_exposure_ratio=0.1):
        """
        根据账户总价值计算目标仓位大小
        """
        total_value = self.broker.getvalue()
        target_value = total_value * target_exposure_ratio
        current_position_value = self.hold_shares * self.close[0]
        value_to_add = target_value - current_position_value

        if value_to_add > 0:
            available_cash = self._cash_available()
            actual_value_to_add = min(value_to_add, available_cash)
            return actual_value_to_add / self.close[0]
        else:
            # 需要减仓
            shares_to_sell = abs(value_to_add) / self.close[0]
            return -shares_to_sell

    def _cash_available(self):
        return self.broker.getcash() - self.p.min_cash_buffer

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        dt = self.datas[0].datetime.date(0)
        if order.status == order.Completed:
            ex_size = order.executed.size
            ex_price = order.executed.price

            avg_cost = (self.hold_cost / self.hold_shares) if self.hold_shares > 0 else 0.0

            self.hold_shares += ex_size
            self.hold_cost += ex_size * ex_price

            realized = 0.0
            if ex_size < 0:
                realized = -ex_size * (ex_price - avg_cost)
                self.realized_pnl += realized

            if self.hold_shares < 1e-12:
                self.hold_shares = 0.0
                self.hold_cost = 0.0

            # 更新历史最高持仓
            if self.hold_shares > self.max_hold_shares:
                self.max_hold_shares = self.hold_shares

            self.log(f"{dt} {'BUY' if ex_size > 0 else 'SELL'} 成交: qty={ex_size:.4f} @ {ex_price:.4f} "
                     f"| realized={realized:.2f}, hold_shares={self.hold_shares:.4f}, hold_cost={self.hold_cost:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order {order.Status[order.status]}")

        self.order = None

    def next(self):
        nav = float(self.close[0])
        date = self.datas[0].datetime.date(0)
        vol = self.data.volume[0]
        sma = self.vol_sma[0]
        self.vol_ratio = vol / sma if sma > 0 else 0.0
        self.signal = '无'
        trend_score = self.score.score[0]
        trend = self.score.trend[0]

        # 初始建仓
        if self.start_nav is None and self.p.function == 'trend':
            # 如果满足建仓条件或者策略运行了一段时间仍未能建仓
            if self._is_good_entry_point() or len(self) > 5:
                amt = min(self.p.initial_amount, self._cash_available())
                if amt > 0:
                    size = amt / nav
                    self.order = self.buy(size=size)
                self.start_nav = nav
                self.start_value = self.broker.getvalue()
                self.log(f"{date} 开始建仓：NAV={nav:.4f}, 投资 {amt:.2f}")
                return
            else:
                self.log(f"{date} 等待合适建仓时机：NAV={nav:.4f}")
                return

        # 更新连续涨跌天数
        if self.close[0] > self.close[-1]:
            self.consecutive_up_days += 1
            self.consecutive_down_days = 0
        elif self.close[0] < self.close[-1]:
            self.consecutive_down_days += 1
            self.consecutive_up_days = 0
        else:
            self.consecutive_up_days = 0
            self.consecutive_down_days = 0

        # 计算日内涨幅
        prev_close = float(self.close[-1]) if len(self.data) > 1 else nav

        pos = self.getposition()
        cash_avail = self._cash_available()

        # 成交量相关判断
        volume_breakout = self._is_volume_breakout()
        volume_shrink = self._is_volume_shrink()
        bullish_divergence = self._is_bullish_volume_divergence()
        bearish_divergence = self._is_bearish_volume_divergence()

        # ========== 策略主逻辑 ==========

        # 1. 强势上升趋势 - 积极加仓
        if  trend == 2:
            add_ratio = 2  # 1.0-2.0倍基础金额

            # 如果伴随放量突破，进一步增加仓位
            if volume_breakout:
                add_ratio *= 1.2

            amt = min(self.p.daily_amount * add_ratio, cash_avail)
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} 强势上升趋势，积极加仓 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"强势上升趋势，建议积极加仓 {amt:.2f}"

        # 3. 弱势上升趋势 - 稳健加仓
        elif trend == 1:
            # 如果出现看涨背离，增加信心
            multiplier = 1.5 if bullish_divergence else 1.0
            amt = min(self.p.daily_amount * multiplier, cash_avail)
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} 弱势上升趋势，稳健加仓 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"弱势上升趋势，建议稳健加仓 {amt:.2f}"

        elif trend == 0:
            # 盘整市场采用网格交易或区间交易
            bb_top = self.boll.lines.top[0]
            bb_bot = self.boll.lines.bot[0]

            # 低位买入
            if nav <= bb_bot * 1.02:
                # 如果出现看涨背离，增加买入力度
                amt_multiplier = 1.5 if bullish_divergence else 1.0
                amt = min(self.p.daily_amount * amt_multiplier, cash_avail)  # 减少投入
                if amt > 0 and self.p.function == 'trend':
                    size = amt / nav
                    self.buy(size=size)
                    self.log(f"{date} 震荡市低位吸纳 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"震荡市，建议低位吸纳 {amt:.2f}"

            # 高位卖出
            elif nav >= bb_top * 0.98:
                # 如果出现看跌背离或放量滞涨，增加卖出力度
                sell_multiplier = 1.5 if (bearish_divergence or volume_shrink) else 1.0
                if pos.size > 0 and self.p.function == 'trend':
                    size_to_sell = pos.size * self.p.sell_fraction_on_high * sell_multiplier
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(f"{date} 震荡市高位减持 {size_to_sell:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"震荡市，建议高位减持 {self.p.sell_fraction_on_high:.2%} 仓位"

        # 6. 强势下降趋势 - 快速减仓
        elif trend == -2:
            # 超买时增加减仓
            min_allowed = self.max_hold_shares * self.p.bottom_ratio
            can_reduce = max(0.0, pos.size - min_allowed)
            reduce_step = self.p.reduce_step * 2
            # 如果出现放量下跌，进一步增加减仓力度
            if volume_breakout:
                reduce_step *= 1.5
            reduce_ratio = min(1.0, reduce_step)
            size_to_sell = min(pos.size * reduce_ratio, can_reduce)
            if pos.size > 0 and self.p.function == 'trend' and can_reduce > 0:
                if size_to_sell > 0:
                    self.sell(size=size_to_sell)
                    self.log(
                        f"{date} 强势下降趋势，快速减仓 {size_to_sell:.4f} 份 @ {nav:.4f} (保留底仓 {min_allowed:.4f})")
            elif self.p.function == 'suggestion':
                self.signal = f"强势下降趋势，建议快速减仓 {self.p.reduce_step * 3:.2%} 仓位"

        # 7. 弱势下降趋势 - 缓慢减仓
        elif trend == -1:
            # 如果出现看涨背离，减缓减仓速度
            reduce_multiplier = 0.5 if bullish_divergence else 1.0
            if pos.size > 0 and self.p.function == 'trend':
                min_allowed = self.max_hold_shares * self.p.bottom_ratio
                can_reduce = max(0.0, pos.size - min_allowed)
                if can_reduce > 0:
                    size_to_sell = min(pos.size * self.p.reduce_step * reduce_multiplier, can_reduce)
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(
                            f"{date} 弱势下降趋势，缓慢减仓 {size_to_sell:.4f} 份 @ {nav:.4f} (保留底仓 {min_allowed:.4f})")
            elif self.p.function == 'suggestion':
                self.signal = f"弱势下降趋势，建议缓慢减仓 {self.p.reduce_step:.2%} 仓位"

    def stop(self):
        nav = float(self.close[0])
        hold_value = self.hold_shares * nav
        unrealized = hold_value - self.hold_cost
        total_realized = self.realized_pnl
        trend = self.score.trend[0]

        if self.hold_cost > 0:
            hold_roi = (hold_value - self.hold_cost) / self.hold_cost
        else:
            hold_roi = None

        if self.p.function != 'suggestion':
            self.log("\n=== 回测结果 ===")
            self.log(f"最终日期: {self.datas[0].datetime.date(0)}")
            self.log(f"持仓份额: {self.hold_shares:.4f}")
            self.log(f"持仓成本(total): {self.hold_cost:.2f}")
            self.log(f"持仓市值: {hold_value:.2f}")
            self.log(f"未实现 PnL: {unrealized:.2f}")
            self.log(f"已实现 PnL: {total_realized:.2f}")
            if hold_roi is not None:
                self.log(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            else:
                self.log("仅仓位收益率 (hold ROI): N/A (无持仓成本)")
            self.log(f"总资金 (broker): {self.broker.getvalue():.2f}")
            self.log("================\n")

        if not self.p.full_log and 'trend' in self.p.function:
            print(f"持仓市值: {hold_value:.2f}")
            if hold_roi is not None:
                print(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            print(f"总资金 (broker): {self.broker.getvalue():.2f}")

        if trend == 2:
            trend_name = '强势上升；'
        if trend == 1:
            trend_name = '弱势上升；'
        if trend == 0:
            trend_name = '盘整；'
        if trend == -1:
            trend_name = '强势下降；'
        if trend == -2:
            trend_name = '弱势下降；'

        trend = f'无' if trend_name == '' else f'{trend_name[:-1]}'

        if self._is_volume_breakout():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 放量'
        elif self._is_volume_shrink():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 缩量'
        elif self._is_bullish_volume_divergence():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 看涨量价背离'
        elif self._is_bearish_volume_divergence():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 看跌量价背离'
        else:
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 正常'

    def get_signal(self):
        return self.signal

class OptimizedTaStrategy(bt.Strategy):
    """
    优化后的 TaStrategy 策略，改进了趋势判断算法、增强了指标可靠性并优化了加减仓逻辑
    """
    params = dict(
        initial_amount=1000.0,  # 初始建仓金额（元）
        daily_amount=200.0,  # 每日基准投金额（元）
        add_on_pullback_ratio=1.5,  # 上升趋势回踩追加比例
        sell_fraction_on_high=0.10,  # 高位卖出仓位比例
        reduce_step=0.10,  # 下跌趋势每次减仓比例
        bottom_ratio=0.10,  # 保留历史最大持仓比例
        sell_on_high_pct=0.05,  # 高位卖出触发阈值
        osc_band_tol=0.02,  # 均线"纠缠"容差
        min_cash_buffer=0.0,  # 保留最小现金缓冲
        function='suggestion',  # 'trend' 用于回测，'suggestion' 用于生成建议
        full_log=False,
    )

    def __init__(self):
        # 基础数据
        self.close = self.datas[0].close
        self.low = self.datas[0].low
        self.high = self.datas[0].high
        self.open = self.datas[0].open
        self.volume = self.datas[0].volume
        self.vol_ratio = 0.0

        # 多周期均线系统
        self.ma_short = bt.ind.SMA(self.datas[0], period=5)
        self.ma_mid = bt.ind.SMA(self.datas[0], period=10)
        self.ma_long = bt.ind.SMA(self.datas[0], period=20)

        # EMA系统增强趋势判断
        self.ema_fast = bt.indicators.EMA(self.data.close, period=9)
        self.ema_medium = bt.indicators.EMA(self.data.close, period=21)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=50)

        # 布林带
        self.bbands = bt.ind.BollingerBands(self.datas[0], period=20)

        # MACD
        self.macd = bt.indicators.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)
        self.macd_hist = self.macd.macd - self.macd.signal

        # RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

        # ATR
        self.atr = bt.indicators.ATR(self.data, period=14)

        # KDJ
        self.stoch = bt.indicators.Stochastic(self.data, period=14, period_dfast=3, period_dslow=3)
        self.kdj_k = self.stoch.percK
        self.kdj_d = self.stoch.percD
        self.kdj_j = 3 * self.kdj_k - 2 * self.kdj_d

        # ADX 增强趋势强度判断
        self.adx = bt.indicators.ADX(self.data, period=14)
        self.di_plus = bt.ind.PlusDI(period=14)
        self.di_minus = bt.ind.MinusDI(period=14)

        # 动量指标
        self.momentum = bt.indicators.Momentum(self.data.close, period=10)

        # 价格行为指标
        self.price_change = self.data.close - self.data.close(-1)  # 日变化
        self.volatility = bt.indicators.StandardDeviation(self.data.close, period=10)  # 波动率

        # 成交量相关指标
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)  # 成交量20日均线

        self.signal = None
        self.indicators = None

        # 持仓管理
        self.hold_shares = 0.0
        self.hold_cost = 0.0
        self.realized_pnl = 0.0
        self.max_hold_shares = 0.0

        # 订单跟踪
        self.order = None

        # 状态跟踪
        self.start_nav = None
        self.start_value = None
        self.consecutive_up_days = 0  # 连续上涨天数
        self.consecutive_down_days = 0  # 连续下跌天数

    def log(self, txt):
        if self.p.function == 'trend' and self.p.full_log and len(self) > 250:
            print(txt)

    def _is_strong_up_trend(self):
        """
        强势上升趋势判断
        """
        # 多均线多头排列且价格在均线上方
        ma_aligned = (self.ma_short[0] > self.ma_mid[0] > self.ma_long[0] and
                      self.ema_fast[0] > self.ema_medium[0] > self.ema_slow[0])

        # 价格在短期均线上方
        price_above_ma = self.close[0] > self.ma_short[0]

        # ADX表明趋势强劲 (>25表示趋势强劲)
        strong_trend = self.adx[0] > 25

        # 正动量
        positive_momentum = self.momentum[0] > 0

        return ma_aligned and price_above_ma and strong_trend and positive_momentum

    def _is_weak_up_trend(self):
        """
        弱势上升趋势判断
        """
        # 至少短期均线多头排列
        ma_weak_aligned = self.ma_short[0] > self.ma_mid[0] > self.ma_long[0]

        # 价格在中期均线上方
        price_above_mid = self.close[0] > self.ma_mid[0]

        # 动量为正但较弱
        weak_momentum = self.momentum[0] > 0

        return ma_weak_aligned and price_above_mid and weak_momentum

    def _is_strong_down_trend(self):
        """
        强势下降趋势判断
        """
        # 多均线空头排列且价格在均线下方
        ma_aligned = (self.ma_short[0] < self.ma_mid[0] < self.ma_long[0] and
                      self.ema_fast[0] < self.ema_medium[0] < self.ema_slow[0])

        # 价格在中期均线下方
        price_below_mid = self.close[0] < self.ma_mid[0]

        # ADX表明趋势强劲
        strong_trend = self.adx[0] > 25

        # 负动量
        negative_momentum = self.momentum[0] < 0

        return ma_aligned and price_below_mid and strong_trend and negative_momentum

    def _is_weak_down_trend(self):
        """
        弱势下降趋势判断
        """
        # 至少短期均线空头排列
        ma_weak_aligned = self.ma_short[0] < self.ma_mid[0] < self.ma_long[0]

        # 价格在短期均线下方
        price_below_short = self.close[0] < self.ma_short[0]

        # 动量为负但较弱
        weak_momentum = self.momentum[0] < 0

        return ma_weak_aligned and price_below_short and weak_momentum

    def _is_consolidation(self):
        """
        判断是否处于震荡整理状态
        """
        # ADX较低表明无明显趋势 (<20表示震荡)
        low_adx = self.adx[0] < 20

        # 均线纠缠
        ma_diff = abs(self.ma_short[0] - self.ma_mid[0]) / self.close[0]
        narrow_bands = ma_diff < self.p.osc_band_tol

        # 波动率较低
        volatility_sum = 0.0
        for i in range(10):
            volatility_sum += self.volatility[-i]
        avg_volatility = volatility_sum / 10
        low_volatility = self.volatility[0] < avg_volatility * 0.8

        return low_adx or narrow_bands or low_volatility

    def _is_consolidation_new(self):
        """更专业、更稳定的震荡判定"""

        close = self.close[0]

        # --- 1. 趋势强度弱 ---
        low_adx = self.adx[0] < 22
        di_diff_small = abs(self.di_plus[0] - self.di_minus[0]) < 5
        weak_trend = low_adx or di_diff_small

        # --- 2. 均线纠缠（距离 + 斜率）---
        ma5, ma10, ma20 = self.ma_short[0], self.ma_mid[0], self.ma_long[0]

        ma_distance_small = (
                abs(ma5 - ma10) / close < 0.01 and
                abs(ma10 - ma20) / close < 0.01
        )

        # slope = today_ma20 - yesterday_ma20
        ma20_slope = abs(self.ma_long[0] - self.ma_long[-1]) / close
        slope_flat = ma20_slope < 0.003

        ma_converged = ma_distance_small and slope_flat

        # --- 3. 价格在区间（布林带）---
        mid = self.bbands.lines.mid[0]
        up = self.bbands.lines.top[0]

        price_in_middle_band = (close > mid - (up - mid) / 2) and (close < mid + (up - mid) / 2)

        # --- 4. 波动率稳定（可选）---
        vol_window = [self.volatility[-i] for i in range(10)]
        vol_stable = np.std(vol_window) < np.mean(vol_window) * 0.8

        # --- 最终判断 ---
        return weak_trend and ma_converged and price_in_middle_band

    def _is_overbought(self):
        """
        超买判断
        """
        rsi_overbought = self.rsi[0] > 70
        kdj_overbought = self.kdj_j[0] > 80
        price_at_top_bb = self.close[0] > self.bbands.lines.top[0]

        return rsi_overbought or kdj_overbought or price_at_top_bb

    def _is_oversold(self):
        """
        超卖判断
        """
        rsi_oversold = self.rsi[0] < 30
        kdj_oversold = self.kdj_j[0] < 20
        price_at_bottom_bb = self.close[0] < self.bbands.lines.bot[0]

        return rsi_oversold or kdj_oversold or price_at_bottom_bb

    def _is_volume_breakout(self):
        """
        判断是否有放量突破
        """
        # 成交量是近期平均的2倍以上
        high_volume = self.vol_ratio > 2.0

        # 同时价格上涨
        price_increase = self.close[0] > self.close[-1]

        return high_volume and price_increase

    def _is_volume_shrink(self):
        """
        判断是否缩量
        """
        # 成交量低于平均值的50%
        low_volume = 0.0 < self.vol_ratio < 0.5
        return low_volume

    def _is_bullish_volume_divergence(self):
        """
        判断是否存在看涨的量价背离
        价格创新低但成交量放大
        """
        # 价格创近期新低
        recent_low_price = min([self.close[-i] for i in range(1, 6)])
        price_new_low = self.close[0] < recent_low_price

        # 但成交量放大
        volume_increase = self.vol_ratio > 1.5

        return price_new_low and volume_increase

    def _is_bearish_volume_divergence(self):
        """
        判断是否存在看跌的量价背离
        价格创新高但成交量萎缩
        """
        # 价格创近期新高
        recent_high_price = max([self.close[-i] for i in range(1, 6)])
        price_new_high = self.close[0] > recent_high_price

        # 但成交量萎缩
        volume_shrink = 0.0 < self.vol_ratio < 0.7

        return price_new_high and volume_shrink

    def _is_good_entry_point(self):
        """
        判断是否为良好的建仓时机，返回建仓比例
        0: 不建仓
        1: 建仓 x1
        2: 建仓 x2
        """
        score = 0

        # 条件1: 处于超卖状态 (+1分)
        if self._is_oversold():
            score += 1

        # 条件2: 动量指标开始转正 (+1分)
        if self.momentum[0] > self.momentum[-1] and self.momentum[0] > 0:
            score += 1

        # 条件3: 价格在布林下轨附近 (+1分)
        if self.close[0] <= self.bbands.lines.bot[0] * 1.02:
            score += 1

        # 条件4: 成交量放大（有资金流入迹象）(+1分)
        if self.vol_ratio > 1.0:
            score += 1

        # 根据得分确定建仓比例
        if score >= 3:
            # 很好的建仓时机，建仓x2
            return 2
        elif score >= 2:
            # 较好的建仓时机，建仓x1
            return 1
        else:
            # 不适合建仓
            return 0

    def _calculate_position_size(self, target_exposure_ratio=0.1):
        """
        根据账户总价值计算目标仓位大小
        """
        total_value = self.broker.getvalue()
        target_value = total_value * target_exposure_ratio
        current_position_value = self.hold_shares * self.close[0]
        value_to_add = target_value - current_position_value

        if value_to_add > 0:
            available_cash = self._cash_available()
            actual_value_to_add = min(value_to_add, available_cash)
            return actual_value_to_add / self.close[0]
        else:
            # 需要减仓
            shares_to_sell = abs(value_to_add) / self.close[0]
            return -shares_to_sell

    def _cash_available(self):
        return self.broker.getcash() - self.p.min_cash_buffer

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        dt = self.datas[0].datetime.date(0)
        if order.status == order.Completed:
            ex_size = order.executed.size
            ex_price = order.executed.price

            avg_cost = (self.hold_cost / self.hold_shares) if self.hold_shares > 0 else 0.0

            self.hold_shares += ex_size
            self.hold_cost += ex_size * ex_price

            realized = 0.0
            if ex_size < 0:
                realized = -ex_size * (ex_price - avg_cost)
                self.realized_pnl += realized

            if self.hold_shares < 1e-12:
                self.hold_shares = 0.0
                self.hold_cost = 0.0

            # 更新历史最高持仓
            if self.hold_shares > self.max_hold_shares:
                self.max_hold_shares = self.hold_shares

            self.log(f"{dt} {'BUY' if ex_size > 0 else 'SELL'} 成交: qty={ex_size:.4f} @ {ex_price:.4f} "
                     f"| realized={realized:.2f}, hold_shares={self.hold_shares:.4f}, hold_cost={self.hold_cost:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order {order.Status[order.status]}")

        self.order = None

    def next(self):
        nav = float(self.close[0])
        date = self.datas[0].datetime.date(0)
        vol = self.data.volume[0]
        sma = self.vol_sma[0]
        self.vol_ratio = vol / sma if sma > 0 else 0.0
        self.signal = '无'
        entry_score = self._is_good_entry_point()

        # 初始建仓
        entry_amt = self.p.initial_amount * entry_score
        if self.start_nav is None and self.p.function == 'trend':
            # 如果满足建仓条件或者策略运行了一段时间仍未能建仓
            if entry_score > 0 or len(self) > 5:
                amt = min(entry_amt, self._cash_available())
                if amt > 0:
                    size = amt / nav
                    self.order = self.buy(size=size)
                self.start_nav = nav
                self.start_value = self.broker.getvalue()
                self.log(f"{date} 开始建仓：NAV={nav:.4f}, 投资 {amt:.2f}")
                return
            else:
                self.log(f"{date} 等待合适建仓时机：NAV={nav:.4f}")
                return
        elif self.p.function == 'suggestion' and entry_score > 0:
            self.signal = f'建议建仓：{entry_amt:.2f}'

        # 更新连续涨跌天数
        if self.close[0] > self.close[-1]:
            self.consecutive_up_days += 1
            self.consecutive_down_days = 0
        elif self.close[0] < self.close[-1]:
            self.consecutive_down_days += 1
            self.consecutive_up_days = 0
        else:
            self.consecutive_up_days = 0
            self.consecutive_down_days = 0

        # 计算日内涨幅
        prev_close = float(self.close[-1]) if len(self.data) > 1 else nav

        pos = self.getposition()
        cash_avail = self._cash_available()

        # 获取各指标值
        bb_top = self.bbands.lines.top[0]
        bb_bot = self.bbands.lines.bot[0]

        # 趋势判断
        strong_up_trend = self._is_strong_up_trend()
        weak_up_trend = self._is_weak_up_trend()
        strong_down_trend = self._is_strong_down_trend()
        weak_down_trend = self._is_weak_down_trend()
        consolidation = self._is_consolidation()
        overbought = self._is_overbought()
        oversold = self._is_oversold()

        # 成交量相关判断
        volume_breakout = self._is_volume_breakout()
        volume_shrink = self._is_volume_shrink()
        bullish_divergence = self._is_bullish_volume_divergence()
        bearish_divergence = self._is_bearish_volume_divergence()

        # ========== 策略主逻辑 ==========

        # 1. 强势上升趋势 - 积极加仓
        if strong_up_trend and not overbought:
            # 根据趋势强度调整加仓比例
            trend_strength = min(1.0, self.adx[0] / 50.0)  # 归一化AD值到0-1
            add_ratio = 2 * (1.0 + trend_strength)  # 1.0-2.0倍基础金额

            # 如果伴随放量突破，进一步增加仓位
            if volume_breakout:
                add_ratio *= 1.2

            increase_amt = self.p.daily_amount * add_ratio
            amt = min(increase_amt, cash_avail)
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} 强势上升趋势，积极加仓 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"强势上升趋势，建议积极加仓 {increase_amt:.2f}"

        # 2. 强势上升但超买的情况 - 适度加仓
        elif strong_up_trend and overbought:
            # 在强势上升趋势中，即使超买也可以适度加仓

            # 但如果出现看跌背离，则减少加仓
            multiplier = 0.5 if bearish_divergence else 1.0
            increase_amt = self.p.daily_amount * multiplier
            amt = min(increase_amt, cash_avail)  # 减少加仓比例
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} 强势上升趋势(超买)，适度加仓 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"强势上升趋势(超买)，建议适度加仓 {increase_amt:.2f}"

        # 3. 弱势上升趋势 - 稳健加仓
        elif weak_up_trend and not overbought:
            # 如果出现看涨背离，增加信心
            multiplier = 1.5 if bullish_divergence else 1.0
            increase_amt = self.p.daily_amount * multiplier
            amt = min(increase_amt, cash_avail)
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} 弱势上升趋势，稳健加仓 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"弱势上升趋势，建议稳健加仓 {increase_amt:.2f}"

        # 4. 回调买入机会 - 在上升趋势中的超卖位置
        elif (strong_up_trend or weak_up_trend) and oversold:
            # 如果缩量回调，更加确认回调性质
            extra_multiplier = 1.2 if volume_shrink else 1.0
            increase_amt = self.p.daily_amount * self.p.add_on_pullback_ratio * extra_multiplier
            extra = min(self.p.daily_amount * self.p.add_on_pullback_ratio * extra_multiplier, cash_avail)
            if extra > 0 and cash_avail > 0 and self.p.function == 'trend':
                size = extra / nav
                self.buy(size=size)
                self.log(f"{date} 上升趋势回调，低吸 {extra:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"上升趋势回调，建议低吸 {increase_amt:.2f}"

        # 5. 震荡市 - 高抛低吸
        elif consolidation:
            # 低位买入
            if (nav <= bb_bot or oversold) and not (strong_down_trend or weak_down_trend):
                # 如果出现看涨背离，增加买入力度
                amt_multiplier = 1.5 if bullish_divergence else 1.0
                increase_amt = self.p.daily_amount * amt_multiplier
                amt = min(increase_amt, cash_avail)  # 减少投入
                if amt > 0 and self.p.function == 'trend':
                    size = amt / nav
                    self.buy(size=size)
                    self.log(f"{date} 震荡市低位吸纳 {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"震荡市，建议低位吸纳 {increase_amt:.2f}"

            # 高位卖出
            elif (nav >= bb_top or overbought) and not (strong_up_trend or weak_up_trend):
                # 如果出现看跌背离或放量滞涨，增加卖出力度
                sell_multiplier = 1.5 if (bearish_divergence or volume_shrink) else 1.0
                reduce_step = self.p.reduce_step * sell_multiplier
                if pos.size > 0 and self.p.function == 'trend':
                    size_to_sell = pos.size * reduce_step
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(f"{date} 震荡市高位减持 {size_to_sell:.4f} 份 @ {nav:.4f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"震荡市，建议高位减持 {reduce_step:.2%} 仓位"

            # 建仓条件：在震荡市中出现好的买入点
            elif entry_score > 0:
                amt = min(entry_amt, self._cash_available())
                if self.start_nav is None and amt > 0 and self.p.function == 'trend':
                    size = amt / nav
                    self.buy(size=size)
                    self.start_nav = nav
                    self.start_value = self.broker.getvalue()
                    self.log(f"{date} 震荡市中发现建仓机会，投资 {amt:.2f}")
                elif self.p.function == 'suggestion':
                    self.signal = f"震荡市，发现建仓机会，建议投资 {entry_amt:.2f}"

        # 6. 强势下降趋势 - 快速减仓
        elif strong_down_trend:
            # 超买时增加减仓
            min_allowed = self.max_hold_shares * self.p.bottom_ratio
            can_reduce = max(0.0, pos.size - min_allowed)
            reduce_step = self.p.reduce_step * 3 if overbought else self.p.reduce_step * 2
            # 如果出现放量下跌，进一步增加减仓力度
            if volume_breakout:
                reduce_step *= 1.5
            reduce_ratio = min(1.0, reduce_step)
            size_to_sell = min(pos.size * reduce_ratio, can_reduce)
            if pos.size > 0 and self.p.function == 'trend' and can_reduce > 0:
                if size_to_sell > 0:
                    self.sell(size=size_to_sell)
                    self.log(
                        f"{date} 强势下降趋势，快速减仓 {size_to_sell:.4f} 份 @ {nav:.4f} (保留底仓 {min_allowed:.4f})")
            elif self.p.function == 'suggestion':
                self.signal = f"强势下降趋势，建议快速减仓 {reduce_step:.2%} 仓位"

        # 7. 弱势下降趋势 - 缓慢减仓
        elif weak_down_trend:
            # 如果出现看涨背离，减缓减仓速度
            reduce_multiplier = 0.5 if bullish_divergence else 1.0
            reduce_step = self.p.reduce_step * reduce_multiplier
            if pos.size > 0 and self.p.function == 'trend':
                min_allowed = self.max_hold_shares * self.p.bottom_ratio
                can_reduce = max(0.0, pos.size - min_allowed)
                if can_reduce > 0:
                    size_to_sell = min(pos.size * reduce_step, can_reduce)
                    if size_to_sell > 0:
                        self.sell(size=size_to_sell)
                        self.log(
                            f"{date} 弱势下降趋势，缓慢减仓 {size_to_sell:.4f} 份 @ {nav:.4f} (保留底仓 {min_allowed:.4f})")
            elif self.p.function == 'suggestion':
                self.signal = f"弱势下降趋势，建议缓慢减仓 {reduce_step:.2%} 仓位"

    def stop(self):
        nav = float(self.close[0])
        hold_value = self.hold_shares * nav
        unrealized = hold_value - self.hold_cost
        total_realized = self.realized_pnl

        if self.hold_cost > 0:
            hold_roi = (hold_value - self.hold_cost) / self.hold_cost
        else:
            hold_roi = None

        if self.p.function != 'suggestion':
            self.log("\n=== 回测结果 ===")
            self.log(f"最终日期: {self.datas[0].datetime.date(0)}")
            self.log(f"持仓份额: {self.hold_shares:.4f}")
            self.log(f"持仓成本(total): {self.hold_cost:.2f}")
            self.log(f"持仓市值: {hold_value:.2f}")
            self.log(f"未实现 PnL: {unrealized:.2f}")
            self.log(f"已实现 PnL: {total_realized:.2f}")
            if hold_roi is not None:
                self.log(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            else:
                self.log("仅仓位收益率 (hold ROI): N/A (无持仓成本)")
            self.log(f"总资金 (broker): {self.broker.getvalue():.2f}")
            self.log("================\n")

        if not self.p.full_log and 'trend' in self.p.function:
            print(f"持仓市值: {hold_value:.2f}")
            if hold_roi is not None:
                print(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            print(f"总资金 (broker): {self.broker.getvalue():.2f}")

        ma = f'MA5={self.ma_short[0]:.4f}, MA10={self.ma_mid[0]:.4f}, MA20={self.ma_long[0]:.4f}'
        price = f'CLOSE={self.close[0]:.4f}'
        adx = f'ADX={self.adx[0]:.4f}'
        momentum = f'MOM={self.momentum[0]:.4f}'
        rsi = f'RSI={self.rsi[0]:.4f}'
        kdj = f'KDJ={self.kdj_j[0]:.4f}'
        bb = f'BOLL: {self.bbands.lines.mid[0]:.4f}/{self.bbands.lines.top[0]:.4f}/{self.bbands.lines.bot[0]:.4f}'
        trend_indicators = f'{ma}，{price}，{adx}，{momentum}\n趋势：'
        trend = ''

        if self._is_strong_up_trend():
            trend += '强势上升；'
        if self._is_weak_up_trend():
            trend += '弱势上升；'
        if self._is_consolidation():
            trend += '盘整；'
        if self._is_strong_down_trend():
            trend += '强势下降；'
        if self._is_weak_down_trend():
            trend += '弱势下降；'

        trend = f'{trend_indicators}无' if trend == '' else f'{trend_indicators}{trend[:-1]}'

        if self._is_oversold():
            over = f'{rsi}，{kdj}，{bb}，状态: 超卖'
        elif self._is_overbought():
            over = f'{rsi}，{kdj}，{bb}，状态: 超买'
        else:
            over = f'{rsi}，{kdj}，{bb}，状态: 正常'

        if self._is_volume_breakout():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 放量'
        elif self._is_volume_shrink():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 缩量'
        elif self._is_bullish_volume_divergence():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 看涨量价背离'
        elif self._is_bearish_volume_divergence():
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 看跌量价背离'
        else:
            volume = f'成交量比例：{self.vol_ratio:.2%}，状态: 正常'

        self.indicators = f'{trend}\n{over}\n{volume}'


    def get_signal(self):
        return self.signal

    def get_indicators(self):
        return self.indicators

class NewTrendTaStrategy(bt.Strategy):
    """
    优化后的 TaStrategy 策略，改进了趋势判断算法、增强了指标可靠性并优化了加减仓逻辑
    """
    params = dict(
        initial_amount=1000.0,  # 初始建仓金额（元）
        daily_amount=200.0,  # 每日基准投金额（元）
        add_on_pullback_ratio=1.5,  # 上升趋势回踩追加比例
        sell_fraction_on_high=0.10,  # 高位卖出仓位比例
        reduce_step=0.10,  # 下跌趋势每次减仓比例
        bottom_ratio=0.10,  # 保留历史最大持仓比例
        sell_on_high_pct=0.05,  # 高位卖出触发阈值
        osc_band_tol=0.02,  # 均线"纠缠"容差
        min_cash_buffer=0.0,  # 保留最小现金缓冲
        function='suggestion',  # 'trend' 用于回测，'suggestion' 用于生成建议
        full_log=False,
    )

    def __init__(self):
        # 基础数据
        self.close = self.datas[0].close
        self.low = self.datas[0].low
        self.high = self.datas[0].high
        self.open = self.datas[0].open
        self.volume = self.datas[0].volume
        self.vol_ratio = 0.0
        self.trend_now = ''
        self.trend_prev = ''

        # 多周期均线系统
        self.ma_short = bt.ind.SMA(self.datas[0], period=5)
        self.ma_mid = bt.ind.SMA(self.datas[0], period=10)
        self.ma_long = bt.ind.SMA(self.datas[0], period=20)

        # EMA系统增强趋势判断
        self.ema_fast = bt.indicators.EMA(self.data.close, period=9)
        self.ema_medium = bt.indicators.EMA(self.data.close, period=21)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=50)

        # 布林带
        self.bbands = bt.ind.BollingerBands(self.datas[0], period=20)
        self.bb_top = self.bbands.lines.top
        self.bb_bot = self.bbands.lines.bot

        # MACD
        self.macd = bt.indicators.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)
        self.macd_hist = self.macd.macd - self.macd.signal

        # RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

        # ATR
        self.atr = bt.indicators.ATR(self.data, period=14)

        # KDJ
        self.stoch = bt.indicators.Stochastic(self.data, period=14, period_dfast=3, period_dslow=3)
        self.kdj_k = self.stoch.percK
        self.kdj_d = self.stoch.percD
        self.kdj_j = 3 * self.kdj_k - 2 * self.kdj_d

        # ADX 增强趋势强度判断
        self.adx = bt.indicators.ADX(self.data, period=14)
        self.di_plus = bt.ind.PlusDI(period=14)
        self.di_minus = bt.ind.MinusDI(period=14)

        # 动量指标
        self.momentum = bt.indicators.Momentum(self.data.close, period=10)

        # 价格行为指标
        self.price_change = self.data.close - self.data.close(-1)  # 日变化
        self.volatility = bt.indicators.StandardDeviation(self.data.close, period=10)  # 波动率

        # 成交量相关指标
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)  # 成交量20日均线

        self.signal = None
        self.indicators = None

        # 持仓管理
        self.hold_shares = 0.0
        self.hold_cost = 0.0
        self.realized_pnl = 0.0
        self.max_hold_shares = 0.0

        # 订单跟踪
        self.order = None

        # 状态跟踪
        self.start_nav = None
        self.start_value = None
        self.consecutive_up_days = 0  # 连续上涨天数
        self.consecutive_down_days = 0  # 连续下跌天数

    def log(self, txt):
        if self.p.function == 'trend' and self.p.full_log and len(self) > 250:
            print(txt)

    def _is_strong_up_trend(self):
        """
        强势上升趋势判断
        """
        # 多均线多头排列且价格在均线上方
        ma_aligned = (self.ma_short[0] > self.ma_mid[0] > self.ma_long[0] and
                      self.ema_fast[0] > self.ema_medium[0] > self.ema_slow[0])

        # 价格在短期均线上方
        price_above_ma = self.close[0] > self.ma_short[0]

        # ADX表明趋势强劲 (>25表示趋势强劲)
        strong_trend = self.adx[0] > 25

        # 正动量
        positive_momentum = self.momentum[0] > 0

        return ma_aligned and price_above_ma and strong_trend and positive_momentum

    def _is_weak_up_trend(self):
        """
        弱势上升趋势判断
        """
        # 至少短期均线多头排列
        ma_weak_aligned = self.ma_short[0] > self.ma_mid[0] > self.ma_long[0]

        # 价格在中期均线上方
        price_above_mid = self.close[0] > self.ma_mid[0]

        # 动量为正但较弱
        weak_momentum = self.momentum[0] > 0

        return ma_weak_aligned and price_above_mid and weak_momentum

    def _is_strong_down_trend(self):
        """
        强势下降趋势判断
        """
        # 多均线空头排列且价格在均线下方
        ma_aligned = (self.ma_short[0] < self.ma_mid[0] < self.ma_long[0] and
                      self.ema_fast[0] < self.ema_medium[0] < self.ema_slow[0])

        # 价格在中期均线下方
        price_below_mid = self.close[0] < self.ma_mid[0]

        # ADX表明趋势强劲
        strong_trend = self.adx[0] > 25

        # 负动量
        negative_momentum = self.momentum[0] < 0

        return ma_aligned and price_below_mid and strong_trend and negative_momentum

    def _is_weak_down_trend(self):
        """
        弱势下降趋势判断
        """
        # 至少短期均线空头排列
        ma_weak_aligned = self.ma_short[0] < self.ma_mid[0] < self.ma_long[0]

        # 价格在短期均线下方
        price_below_short = self.close[0] < self.ma_short[0]

        # 动量为负但较弱
        weak_momentum = self.momentum[0] < 0

        return ma_weak_aligned and price_below_short and weak_momentum

    def _is_consolidation(self):
        """
        判断是否处于震荡整理状态
        """
        # ADX较低表明无明显趋势 (<20表示震荡)
        low_adx = self.adx[0] < 20

        # 均线纠缠
        ma_diff = abs(self.ma_short[0] - self.ma_mid[0]) / self.close[0]
        narrow_bands = ma_diff < self.p.osc_band_tol

        # 波动率较低
        volatility_sum = 0.0
        for i in range(10):
            volatility_sum += self.volatility[-i]
        avg_volatility = volatility_sum / 10
        low_volatility = self.volatility[0] < avg_volatility * 0.8

        return low_adx or narrow_bands or low_volatility

    def _is_consolidation_new(self):
        """更专业、更稳定的震荡判定"""

        close = self.close[0]

        # --- 1. 趋势强度弱 ---
        low_adx = self.adx[0] < 22
        di_diff_small = abs(self.di_plus[0] - self.di_minus[0]) < 5
        weak_trend = low_adx or di_diff_small

        # --- 2. 均线纠缠（距离 + 斜率）---
        ma5, ma10, ma20 = self.ma_short[0], self.ma_mid[0], self.ma_long[0]

        ma_distance_small = (
                abs(ma5 - ma10) / close < 0.01 and
                abs(ma10 - ma20) / close < 0.01
        )

        # slope = today_ma20 - yesterday_ma20
        ma20_slope = abs(self.ma_long[0] - self.ma_long[-1]) / close
        slope_flat = ma20_slope < 0.003

        ma_converged = ma_distance_small and slope_flat

        # --- 3. 价格在区间（布林带）---
        mid = self.bbands.lines.mid[0]
        up = self.bbands.lines.top[0]

        price_in_middle_band = (close > mid - (up - mid) / 2) and (close < mid + (up - mid) / 2)

        # --- 4. 波动率稳定（可选）---
        vol_window = [self.volatility[-i] for i in range(10)]
        vol_stable = np.std(vol_window) < np.mean(vol_window) * 0.8

        # --- 最终判断 ---
        return weak_trend and ma_converged and price_in_middle_band

    def _is_overbought(self):
        """
        超买判断
        """
        rsi_overbought = self.rsi[0] > 70
        kdj_overbought = self.kdj_j[0] > 80
        price_at_top_bb = self.close[0] > self.bbands.lines.top[0]

        return rsi_overbought or kdj_overbought or price_at_top_bb

    def _is_oversold(self):
        """
        超卖判断
        """
        rsi_oversold = self.rsi[0] < 30
        kdj_oversold = self.kdj_j[0] < 20
        price_at_bottom_bb = self.close[0] < self.bbands.lines.bot[0]

        return rsi_oversold or kdj_oversold or price_at_bottom_bb

    def _is_volume_breakout(self):
        """
        判断是否有放量突破
        """
        # 成交量是近期平均的2倍以上
        high_volume = self.vol_ratio > 2.0

        # 同时价格上涨
        price_increase = self.close[0] > self.close[-1]

        return high_volume and price_increase

    def _is_volume_shrink(self):
        """
        判断是否缩量
        """
        # 成交量低于平均值的50%
        low_volume = 0.0 < self.vol_ratio < 0.5
        return low_volume

    def _is_bullish_volume_divergence(self):
        """
        判断是否存在看涨的量价背离
        价格创新低但成交量放大
        """
        # 价格创近期新低
        recent_low_price = min([self.close[-i] for i in range(1, 6)])
        price_new_low = self.close[0] < recent_low_price

        # 但成交量放大
        volume_increase = self.vol_ratio > 1.5

        return price_new_low and volume_increase

    def _is_bearish_volume_divergence(self):
        """
        判断是否存在看跌的量价背离
        价格创新高但成交量萎缩
        """
        # 价格创近期新高
        recent_high_price = max([self.close[-i] for i in range(1, 6)])
        price_new_high = self.close[0] > recent_high_price

        # 但成交量萎缩
        volume_shrink = 0.0 < self.vol_ratio < 0.7

        return price_new_high and volume_shrink

    def _is_good_entry_point(self):
        """
        判断是否为良好的建仓时机，返回建仓比例
        0: 不建仓
        1: 建仓 x1
        2: 建仓 x2
        """
        score = 0

        # 条件1: 处于超卖状态 (+1分)
        if self._is_oversold():
            score += 1

        # 条件2: 动量指标开始转正 (+1分)
        if self.momentum[0] > self.momentum[-1] and self.momentum[0] > 0:
            score += 1

        # 条件3: 价格在布林下轨附近 (+1分)
        if self.close[0] <= self.bbands.lines.bot[0] * 1.02:
            score += 1

        # 条件4: 成交量放大（有资金流入迹象）(+1分)
        if self.vol_ratio > 1.0:
            score += 1

        # 根据得分确定建仓比例
        if score >= 3:
            # 很好的建仓时机，建仓x2
            return 2
        elif score >= 2:
            # 较好的建仓时机，建仓x1
            return 1
        else:
            # 不适合建仓
            return 0

    def _calculate_position_size(self, target_exposure_ratio=0.1):
        """
        根据账户总价值计算目标仓位大小
        """
        total_value = self.broker.getvalue()
        target_value = total_value * target_exposure_ratio
        current_position_value = self.hold_shares * self.close[0]
        value_to_add = target_value - current_position_value

        if value_to_add > 0:
            available_cash = self._cash_available()
            actual_value_to_add = min(value_to_add, available_cash)
            return actual_value_to_add / self.close[0]
        else:
            # 需要减仓
            shares_to_sell = abs(value_to_add) / self.close[0]
            return -shares_to_sell

    def _cash_available(self):
        return self.broker.getcash() - self.p.min_cash_buffer

    def _get_trend(self):
        if self._is_strong_up_trend():
            return 'SU'
        elif self._is_weak_up_trend():
            return 'WU'
        elif self._is_consolidation():
            return 'CO'
        elif self._is_strong_down_trend():
            return 'SD'
        elif self._is_weak_down_trend():
            return 'WD'

        return 'UT'

    def _breakout_coming(self):

        # 1. 布林带张口
        bb_width_now = self.bb_top[0] - self.bb_bot[0]
        bb_width_prev = self.bb_top[-5] - self.bb_bot[-5] if len(self) > 5 else 0
        bb_opening = bb_width_now > bb_width_prev * 1.15

        # 2. ATR 波动率上升
        atr_rising = self.atr[0] > self.atr[-3] * 1.10 if len(self) > 3 else False

        # 3. ADX 趋势力量上升
        adx_rising = self.adx[0] > self.adx[-3] + 2 if len(self) > 3 else False

        # 4. 价格突破短均线并形成多空序列
        ma5 = self.ma_short[0]
        ma10 = self.ma_mid[0]
        price_break_ma = (
                (self.data.close[0] > ma5 > ma10) or
                (self.data.close[0] < ma5 < ma10)
        )

        # 5. 放量 (趋势启动常伴随)
        vol_rising = self.data.volume[0] > self.vol_sma[0] * 1.3

        # 满足以上五个信号中的两个 → 趋势可能要来了
        signals = [bb_opening, atr_rising, adx_rising, price_break_ma, vol_rising]
        count = sum(signals)

        return count >= 2

    def _trend_change(self, prev_trend, curr_trend):
        """
        根据趋势状态变化返回操作信号：
        >0 : 加仓金额（倍数 * daily_amount）
        <0 : 减仓比例（如 -1 表示减 10% ）
         0 : 不操作
        """
        # ==========================
        # 趋势定义：
        # CO = Consolidation（震荡）
        # WU = Weak Up（弱上升）
        # SU = Strong Up（强上升）
        # WD = Weak Down（弱下降）
        # SD = Strong Down（强下降）
        # ==========================

        # 如果今天趋势无变化（常态保持）
        if prev_trend == curr_trend:
            if curr_trend == "WU":
                return 0.5, "趋势保持弱升，小加仓"  # 弱升维持 → 小加仓
            elif curr_trend == "WD":
                return -1, "趋势保持弱跌，小减仓"  # 弱跌维持 → 小减仓
            elif curr_trend == "SU":
                return 0.5, "趋势保持强升，轻加仓"  # 强升维持 → 轻加仓
            elif curr_trend == "SD":
                return -2, "趋势保持强跌，大幅减仓"  # 强跌维持 → 大幅减仓
            # elif curr_trend == "CO":
            #     return 0, "震荡保持"
            # else:
            #     return 0, "无操作"

        # ======================================================
        # 以下为趋势发生变化的情况
        # ======================================================

        # ===== 上升方向 =====
        if prev_trend == "CO" and curr_trend == "WU":
            return 1, "震荡→弱升，试探性建仓"

        if prev_trend == "WU" and curr_trend == "SU":
            return 2, "弱升→强升，加速加仓"

        if prev_trend == "CO" and curr_trend == "SU":
            return 3, "震荡→强升，强力建仓（有效突破）"

        if prev_trend == "SU" and curr_trend == "WU":
            return -1, "弱升→震荡，减仓 10%"

        if prev_trend == "WU" and curr_trend == "CO":
            return -1, "弱升→震荡，减仓 10%"

        # SU → CO：强升结束（可能见顶）
        if prev_trend == "SU" and curr_trend == "CO":
            return -2, "强升结束（可能见顶），减仓 20%"

        # ===== 下降方向 =====

        if prev_trend == "CO" and curr_trend == "WD":
            return -3, "震荡转弱跌，减仓 20%"

        if prev_trend == "WD" and curr_trend == "SD":
            return -4, "弱跌转强跌，减仓 40%"

        if prev_trend == "CO" and curr_trend == "SD":
            return -5, "震荡转强跌，减仓 50%"

        if prev_trend == "SD" and curr_trend == "WD":
            return 0, "强跌转弱跌，不加仓（避免抄底）"

        if prev_trend == "WD" and curr_trend == "CO":
            return 0, "弱跌企稳，不加仓（横盘可能继续跌）"

        if prev_trend == "SD" and curr_trend == "CO":
            return 0, "强跌企稳，不加仓（等待趋势反转确认）"

        # ===== 特殊：上下反复的震荡系反转 =====
        if (prev_trend == "WU" and curr_trend == "WD") or \
                (prev_trend == "WD" and curr_trend == "WU"):
            return 0, "上下反复，继续观望"

        break_out_coming = self._breakout_coming()
        if curr_trend == 'CO' and not break_out_coming:
            nav = float(self.close[0])
            oversold = self._is_oversold()
            overbought = self._is_overbought()
            bb_slope = self.bb_top[0] - self.bb_top[-3] if len(self) > 3 else 0
            flat_band = abs(bb_slope) < 0.2 * self.atr[0]
            not_volume_dump = self.data.volume[0] <= self.vol_sma[0] * 1.2
            not_volume_breakout = self.data.volume[0] <= self.vol_sma[0] * 1.3
            low_buy = (nav <= self.bb_bot[0] or oversold) and flat_band and not_volume_dump
            high_sell = (nav >= self.bb_top[0] or overbought) and flat_band and not_volume_breakout
            if low_buy:
                return 1, "震荡市，低位吸纳"
            elif high_sell:
                return -1, "震荡市，高位减持"
            else:
                return 0, f"震荡市，未发现操作点"
        elif curr_trend == 'CO':
            return 0, "震荡市突破中，等待确认"

        # 默认无操作
        return 0, "无操作"

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        dt = self.datas[0].datetime.date(0)
        if order.status == order.Completed:
            ex_size = order.executed.size
            ex_price = order.executed.price

            avg_cost = (self.hold_cost / self.hold_shares) if self.hold_shares > 0 else 0.0

            self.hold_shares += ex_size
            self.hold_cost += ex_size * ex_price

            realized = 0.0
            if ex_size < 0:
                realized = -ex_size * (ex_price - avg_cost)
                self.realized_pnl += realized

            if self.hold_shares < 1e-12:
                self.hold_shares = 0.0
                self.hold_cost = 0.0

            # 更新历史最高持仓
            if self.hold_shares > self.max_hold_shares:
                self.max_hold_shares = self.hold_shares

            self.log(f"{dt} {'BUY' if ex_size > 0 else 'SELL'} 成交: qty={ex_size:.4f} @ {ex_price:.4f} "
                     f"| realized={realized:.2f}, hold_shares={self.hold_shares:.4f}, hold_cost={self.hold_cost:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order {order.Status[order.status]}")

        self.order = None

    def next(self):
        nav = float(self.close[0])
        date = self.datas[0].datetime.date(0)
        self.signal = '无'
        entry_score = self._is_good_entry_point()
        pos = self.getposition()
        cash_avail = self._cash_available()

        # 初始建仓
        entry_amt = self.p.initial_amount * entry_score
        if self.start_nav is None and self.p.function == 'trend':
            # 如果满足建仓条件或者策略运行了一段时间仍未能建仓
            if entry_score > 0 or len(self) > 5:
                amt = min(entry_amt, cash_avail)
                if amt > 0:
                    size = amt / nav
                    self.order = self.buy(size=size)
                self.start_nav = nav
                self.start_value = self.broker.getvalue()
                self.log(f"{date} 开始建仓：NAV={nav:.4f}, 投资 {amt:.2f}")
                return
            else:
                self.log(f"{date} 等待合适建仓时机：NAV={nav:.4f}")
                return
        elif self.p.function == 'suggestion' and entry_score > 0:
            self.signal = f'建议建仓：{entry_amt:.2f}'

        # 判断趋势变化
        trend_ratio = 0
        signal = '无操作'
        self.trend_now = self._get_trend()
        if self.trend_prev:
            trend_ratio, signal = self._trend_change(self.trend_prev, self.trend_now)
        self.trend_prev = self.trend_now

        # ========== 策略主逻辑 ==========

        # 1. 趋势变化加仓
        if trend_ratio > 0:
            add_amt = self.p.daily_amount * trend_ratio
            amt = min(add_amt, cash_avail)
            if amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.log(f"{date} {signal} {amt:.2f} -> {size:.4f} 份 @ {nav:.4f}")
            elif self.p.function == 'suggestion':
                self.signal = f"{signal} {add_amt:.2f}"

        elif trend_ratio < 0:
            min_allowed = self.max_hold_shares * self.p.bottom_ratio
            can_reduce = max(0.0, pos.size - min_allowed)
            reduce_step = self.p.reduce_step * trend_ratio
            size_to_sell = min(pos.size * reduce_step, can_reduce)
            if pos.size > 0 and self.p.function == 'trend' and can_reduce > 0:
                if size_to_sell > 0:
                    self.sell(size=size_to_sell)
                    self.log(
                        f"{date} {signal} {size_to_sell:.4f} 份 @ {nav:.4f} (保留底仓 {min_allowed:.4f})")
            elif self.p.function == 'suggestion':
                self.signal = f"{signal} {reduce_step:.2%} 仓位"

        # 5. 震荡市 - 高抛低吸
        elif self.trend_now == 'CO' and entry_score > 0:
            # 建仓条件：在震荡市中出现好的买入点
            amt = min(entry_amt, self._cash_available())
            if self.start_nav is None and amt > 0 and self.p.function == 'trend':
                size = amt / nav
                self.buy(size=size)
                self.start_nav = nav
                self.start_value = self.broker.getvalue()
                self.log(f"{date} 震荡市中发现建仓机会，投资 {amt:.2f}")
            elif self.p.function == 'suggestion':
                self.signal = f"震荡市，发现建仓机会，建议投资 {entry_amt:.2f}"

        else:
            if self.p.function == 'trend':
                self.log(f"{date} {signal}")
            elif self.p.function == 'suggestion':
                self.signal = f"{signal}"


    def stop(self):
        nav = float(self.close[0])
        hold_value = self.hold_shares * nav
        unrealized = hold_value - self.hold_cost
        total_realized = self.realized_pnl

        if self.hold_cost > 0:
            hold_roi = (hold_value - self.hold_cost) / self.hold_cost
        else:
            hold_roi = None

        if self.p.function != 'suggestion':
            self.log("\n=== 回测结果 ===")
            self.log(f"最终日期: {self.datas[0].datetime.date(0)}")
            self.log(f"持仓份额: {self.hold_shares:.4f}")
            self.log(f"持仓成本(total): {self.hold_cost:.2f}")
            self.log(f"持仓市值: {hold_value:.2f}")
            self.log(f"未实现 PnL: {unrealized:.2f}")
            self.log(f"已实现 PnL: {total_realized:.2f}")
            if hold_roi is not None:
                self.log(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            else:
                self.log("仅仓位收益率 (hold ROI): N/A (无持仓成本)")
            self.log(f"总资金 (broker): {self.broker.getvalue():.2f}")
            self.log("================\n")

        if not self.p.full_log and 'trend' in self.p.function:
            print(f"持仓市值: {hold_value:.2f}")
            if hold_roi is not None:
                print(f"仅仓位收益率 (hold ROI): {hold_roi:.2%}")
            print(f"总资金 (broker): {self.broker.getvalue():.2f}")

        vol = self.data.volume[0]
        sma = self.vol_sma[0]
        self.vol_ratio = vol / sma if sma > 0 else 0.0
        ma = f'MA5={self.ma_short[0]:.4f}, MA10={self.ma_mid[0]:.4f}, MA20={self.ma_long[0]:.4f}'
        price = f'CLOSE={self.close[0]:.4f}'
        adx = f'ADX={self.adx[0]:.4f}'
        momentum = f'MOM={self.momentum[0]:.4f}'
        rsi = f'RSI={self.rsi[0]:.4f}'
        kdj = f'KDJ={self.kdj_j[0]:.4f}'
        bb = f'BOLL: {self.bbands.lines.mid[0]:.4f}/{self.bbands.lines.top[0]:.4f}/{self.bbands.lines.bot[0]:.4f}'
        trend_indicators = f'{ma}，{price}，{adx}，{momentum}\n趋势：'
        trend = self.trend_prev + ' -> ' + self.trend_now

        trend = f'{trend_indicators}无' if trend == '' else f'{trend_indicators} {trend}'

        if self._is_oversold():
            over = f'{rsi}，{kdj}，{bb}，状态: 超卖'
        elif self._is_overbought():
            over = f'{rsi}，{kdj}，{bb}，状态: 超买'
        else:
            over = f'{rsi}，{kdj}，{bb}，状态: 正常'


        vol = f'VOL={self.data.volume[0]}，VMA={self.vol_sma[0]}'
        if self._is_volume_breakout():
            volume = f'{vol} 成交量比例：{self.vol_ratio:.2%}，状态: 放量'
        elif self._is_volume_shrink():
            volume = f'{vol} 成交量比例：{self.vol_ratio:.2%}，状态: 缩量'
        elif self._is_bullish_volume_divergence():
            volume = f'{vol} 成交量比例：{self.vol_ratio:.2%}，状态: 看涨量价背离'
        elif self._is_bearish_volume_divergence():
            volume = f'{vol} 成交量比例：{self.vol_ratio:.2%}，状态: 看跌量价背离'
        else:
            volume = f'{vol} 成交量比例：{self.vol_ratio:.2%}，状态: 正常'

        self.indicators = f'{trend}\n{over}\n{volume}'

    def get_signal(self):
        return self.signal

    def get_indicators(self):
        return self.indicators




def ceboro_suggestion(df, strategy, forecast_nav, forecast_change, indicators=False):
    # 构建 backtrader 数据源
    data = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    strat = cerebro.addstrategy(strategy, function='suggestion', full_log=False)
    try:
        result = cerebro.run()
        signal = result[0].get_signal()

        emojis = {'加仓': '📈', '买入': '🛒', '低吸': '🤿', '减仓': '📉', '卖出': '🏷️', '无': '😐'}
        emoji = next((e for s, e in emojis.items() if s in signal), '😐')

        print(f"📊 预测净值: {forecast_nav:.4f} ({forecast_change:+.2%})")
        print(f"{emoji} 今日操作建议: {signal or '无'}")

        if indicators:
            indicators = result[0].get_indicators()
            print(indicators)
        return signal
    except Exception as e:
        print(f"⚠️ 获取今日操作建议时出错: {e}")
        return '错误'

def ceboro_trend(df, strategy, use_plot, cash, full_log= False):
    data = bt.feeds.PandasData(dataname=df)

    try:
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(strategy, function="trend", full_log=full_log)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days,
                            annualize=True,
                            riskfreerate=0.02)
        cerebro.broker.setcash(cash)
        result = cerebro.run()
        if use_plot:
            cerebro.plot()
        sharpe = result[0].analyzers.sharpe.get_analysis()
        print(f"夏普比率: {sharpe.get('sharperatio', 0):.2f}")
    except Exception as e:
        print(f"⚠️ 回测基金失败: {e}")
        traceback.print_exc()


# === 判断当天操作的函数 ===
def combine_today_info(df, forecast_change):
    """输入df和预估涨跌幅（如0.005代表+0.5%），返回今日操作建议"""
    df_bt = df
    volume = 0
    if df["volume"].isnull().all():
        df_bt["volume"] = 0
    else:
        volume = df["volume"].iloc[-1]
    df_bt["openinterest"] = 0

    last_nav = df['close'].iloc[-1]
    forecast_nav = last_nav * (1 + forecast_change)
    forecast_date = df_bt.index[-1] + pd.Timedelta(days=1)

    new_row = pd.DataFrame({'close': [forecast_nav], 'open': [forecast_nav], 'high': [forecast_nav], 'low': [forecast_nav], "volume": [volume]}, index=[forecast_date])
    df_today = pd.concat([df, new_row])

    return df_today, forecast_nav


def start_trading(code, strategy, cash):
    from utils_efinance import get_fund_history_ef
    df = get_fund_history_ef(code, 1000)

    data = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(strategy, function="trend", full_log=True)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, annualize=True,
                        riskfreerate=0.02)
    cerebro.broker.setcash(cash)
    result = cerebro.run()
    cerebro.plot()
    sharpe = result[0].analyzers.sharpe.get_analysis()
    print(f"夏普比率: {sharpe.get('sharperatio', 0):.2f}")

if __name__ == "__main__":
    code = '014777'
    start_trading(code, OptimizedTaStrategy)
