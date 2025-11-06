import requests
import pandas as pd
from time import sleep
from bs4 import BeautifulSoup
from tqdm import tqdm
import efinance as ef

def get_fund_history(fund_code: str, pages=0):
    """
    从天天基金网抓取指定基金的历史净值数据
    fund_code: 基金代码，如 '005918'
    sleep_sec: 每页请求间隔（防止反爬）
    """
    all_data = []
    page = 1
    base_url = "https://fund.eastmoney.com/f10/F10DataApi.aspx"

    print(f"开始抓取基金 {fund_code} 历史净值...")

    # 第一次请求以获得总页数
    params = {
        "type": "lsjz",
        "code": fund_code,
        "page": page,
        "per": 40
    }
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(base_url, params=params, headers=headers)
    r.encoding = "utf-8"

    # 提取页数
    try:
        total_pages = int(r.text.split("pages:")[1].split(",")[0])
    except:
        total_pages = 1

    if pages > 0:
        total_pages = min(total_pages, pages)

    print(f"基金 {fund_code} 共 {total_pages} 页历史数据")

    # 循环抓取
    for page in tqdm(range(1, total_pages + 1)):
        params["page"] = page
        r = requests.get(base_url, params=params, headers=headers)
        r.encoding = "utf-8"

        # 提取 HTML 表格
        html = r.text.split('content:"')[1].split('",records')[0]
        html = html.replace("\\", "")
        soup = BeautifulSoup(html, "html.parser")

        # 解析每一行
        for tr in soup.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            date = tds[0].text.strip()
            unit = tds[1].text.strip()
            acc = tds[2].text.strip()
            rate = tds[3].text.strip().replace("%", "")
            all_data.append([date, float(unit), float(acc), float(rate) if rate else None])
            sleep(0.1)  # 防止请求过快

    df = pd.DataFrame(all_data, columns=["date", "unit_net", "acc_net", "daily_change"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df

def get_fund_history_ef(fund_code: str, items=1000):
    """
    从 efinance 抓取指定基金的历史净值数据
    fund_code: 基金代码，如 '005918'
    """
    fund_df = ef.fund.get_quote_history(fund_code, items)
    fund_df = fund_df.sort_values('日期').reset_index(drop=True)
    fund_df.rename(
        columns={'日期': 'date', '单位净值': 'close'},
        inplace=True)
    fund_df['open'] = fund_df['close']
    fund_df['high'] = fund_df['close']
    fund_df['low'] = fund_df['close']
    fund_df['volume'] = 0
    return fund_df

def get_stock_history_ef(stock_code: str, beg):
    """
    从 efinance 抓取指定股票的历史行情数据
    stock_code: 股票代码，如 '000001'
    """
    stock_df = ef.stock.get_quote_history(stock_code, beg=beg)
    stock_df = stock_df.sort_values('日期').reset_index(drop=True)
    stock_df.rename(columns={'日期':'date', '收盘': 'close', '开盘': 'open', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)

    return stock_df

def get_realtime_rate(fund_code, etf_code):
    """
    获取基金实时涨跌幅
    fund_code: 基金代码，如 '005918'
    etf_code: 追踪的 ETF/指数代码，如 '159513'
    """
    import math
    e1, e2, e3 = False, False, False
    try:
        fund_info = ef.fund.get_realtime_increase_rate(fund_code)
        fund_rate = fund_info.iloc[-1].get("估算涨跌幅", None)
        name = fund_info.iloc[-1].get("基金名称", None)
        if math.isnan(fund_rate):
            fund_rate = None
        if fund_rate:
            return fund_rate, name
    except Exception as e:
        e1 = True

    try:
        etf_info = ef.stock.get_quote_snapshot(etf_code)
        etf_rate = etf_info.get("涨跌幅", None)
        name = etf_info.get("名称", None)
        if math.isnan(etf_rate):
            etf_rate = None
        if etf_rate:
            return etf_rate, name
    except Exception as e:
        e2 = True

    try:
        etf_history = ef.stock.get_quote_history(etf_code, beg='20250101')
        etf_last_rate = etf_history.iloc[-1].get("涨跌幅", None)
        name = etf_history.iloc[-1].get("股票名称", None)
        if math.isnan(etf_last_rate):
            etf_last_rate = None
        if etf_last_rate:
            return etf_last_rate, name
    except Exception as e:
        e3 = True

    if e1 and e2 and e3:
        print(f"⚠️ 获取 {fund_code} 基金涨跌幅失败: {e}")

    return None, None


if __name__ == "__main__":
    fund_code = "017437"
    # df = get_fund_history(fund_code, 10)
    df = get_fund_history_ef(fund_code, 300)
    print(df.head())
    print(df.tail())

    # 保存
    df.to_csv(f"{fund_code}_history.csv", index=False, encoding="utf-8-sig")
    print(f"✅ 数据已保存为 {fund_code}_history.csv")

if __name__ == "__main__":
    fund_code = "017437"
    etf_code = "159513"
    price = get_realtime_rate(fund_code, etf_code)
    print(price)


