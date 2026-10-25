"""
scripts/update_taiwan_holidays.py — 自動更新台灣股市休市日曆

從 TWSE 官方 API 抓取每年開休市日期，自動更新 config/taiwan_holidays.json。
TWSE 每年 11~12 月公布隔年行事曆，本 script 可抓取任意年份（含今年+明年）。

Usage:
  python scripts/update_taiwan_holidays.py            # 更新今年 + 明年
  python scripts/update_taiwan_holidays.py --years 2025 2026 2027
  python scripts/update_taiwan_holidays.py --year 2026 --dry-run   # 預覽不寫檔
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen

TWSE_URL = "https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear={year}"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "taiwan_holidays.json"


def fetch_twse_calendar(year):
    """從 TWSE 官方 API 抓取指定年份開休市資料，回傳 [{date, name, note}]"""
    url = TWSE_URL.format(year=year)
    try:
        with urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ 抓取 {year} 失敗: {e}")
        return None
    if payload.get("stat") != "ok":
        print(f"❌ {year} 回傳異常: {payload.get('stat')}")
        return None
    rows = []
    for row in payload.get("data", []):
        if len(row) < 2:
            continue
        rows.append({"date": row[0], "name": row[1], "note": row[2] if len(row) > 2 else ""})
    # 檢查回傳資料年份是否與請求相符（TWSE 尚未公布時會回傳去年資料）
    if rows and all(r["date"].startswith(str(year)) for r in rows) is False:
        actual_years = {r["date"][:4] for r in rows}
        print(f"⚠️ {year} 尚未公布，API 回傳 {sorted(actual_years)} 資料，跳過")
        return None
    return rows


def is_trading_day_marker(name):
    """名稱含「開始交易日/最後交易日」→ 當天有交易，非休市"""
    return ("開始交易日" in name) or ("最後交易日" in name)


def build_holidays(rows):
    """從 TWSE 資料推導休市日 + 補班日"""
    holidays = []
    makeup = []
    notes = {}
    for r in rows:
        d = r["date"]
        dt = date.fromisoformat(d)
        if dt.weekday() >= 5:
            continue
        if is_trading_day_marker(r["name"]):
            continue
        holidays.append(d)
        notes[d] = r["name"]
    return sorted(holidays), sorted(makeup), notes


def load_existing():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save(existing, holidays, notes, years):
    existing["holidays"] = sorted(set(holidays))
    existing["makeup_workdays"] = sorted(set(existing.get("makeup_workdays", [])))
    existing["_holiday_notes"] = notes
    existing["_last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing["_source"] = "TWSE 官方 API（scripts/update_taiwan_holidays.py 自動更新）"
    existing["_years_fetched"] = sorted(set(existing.get("_years_fetched", [])) | set(years))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已更新: {CONFIG_PATH}")
    print(f"   休市日: {len(existing['holidays'])} 天")


def main():
    parser = argparse.ArgumentParser(description="自動更新台灣股市休市日曆")
    parser.add_argument("--years", type=int, nargs="*", help="要抓取的年份（預設: 今年+明年）")
    parser.add_argument("--dry-run", action="store_true", help="只預覽不寫檔")
    args = parser.parse_args()

    if args.years:
        years = args.years
    else:
        cur = date.today().year
        years = [cur, cur + 1]

    all_holidays = []
    all_notes = {}
    for year in years:
        rows = fetch_twse_calendar(year)
        if rows is None:
            continue
        holidays, _, notes = build_holidays(rows)
        all_holidays.extend(holidays)
        all_notes.update(notes)
        print(f"📅 {year}: {len(rows)} 筆資料，其中休市 {len(holidays)} 天")
        for h in holidays:
            print(f"   {h}  {notes[h]}")

    if not all_holidays:
        print("❌ 沒有抓到任何資料")
        sys.exit(1)

    if args.dry_run:
        print(f"\n(dry-run) 將寫入 {len(all_holidays)} 個休市日")
        return

    existing = load_existing()
    save(existing, all_holidays, all_notes, years)


if __name__ == "__main__":
    main()
