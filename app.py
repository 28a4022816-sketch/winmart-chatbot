import streamlit as st
import pandas as pd
import json
import os
import re
import urllib.parse
import unicodedata
import google.generativeai as genai

# ==============================================================================
# 1. CẤU HÌNH TRANG & GIAO DIỆN THƯƠNG HIỆU WINMART (CUSTOM CSS)
# ==============================================================================
st.set_page_config(
    page_title="WinMart Smart Shopper | Trợ lý Mua sắm Thông minh",
    page_icon="🛒",
    layout="wide"
)

st.markdown("""
<style>
    .winmart-hero {
        background: linear-gradient(135deg, #D71920 0%, #A30E14 100%);
        padding: 22px 28px;
        border-radius: 14px;
        margin-bottom: 20px;
        box-shadow: 0 6px 18px rgba(215, 25, 32, 0.25);
        border: 1px solid rgba(255, 210, 0, 0.35);
    }
    .winmart-hero h1 {
        color: #FFFFFF !important;
        font-size: 28px !important;
        font-weight: 800 !important;
        margin: 0 0 6px 0 !important;
        letter-spacing: 0.3px;
    }
    .winmart-hero span.brand-gold {
        color: #FFD200;
    }
    .winmart-hero p {
        color: rgba(255, 255, 255, 0.92) !important;
        font-size: 15px !important;
        margin: 0 !important;
    }
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(215, 25, 32, 0.35);
        padding: 14px 18px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(90deg, #D71920 0%, #B8141A 100%);
        border: none;
        border-radius: 10px;
        padding: 10px 24px;
        font-weight: 700;
        font-size: 16px;
        box-shadow: 0 4px 12px rgba(215, 25, 32, 0.3);
        transition: all 0.2s ease;
    }
    div.stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(215, 25, 32, 0.45);
    }
    div.stButton > button[kind="secondary"] {
        border-radius: 20px;
        border: 1px solid rgba(255, 210, 0, 0.45);
        font-size: 14px;
        padding: 6px 14px;
    }
</style>
""", unsafe_allow_html=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==============================================================================
# 2. NẠP & CHUẨN HÓA CƠ SỞ DỮ LIỆU KHUYẾN MÃI
# ==============================================================================
def remove_accents(text: str) -> str:
    if not text:
        return ""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

def parse_price(val, allow_thousands_scale: bool = True) -> int:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0
    if isinstance(val, (int, float)):
        v = int(round(val))
        if allow_thousands_scale and 0 < v < 500:
            return v * 1000
        return v
    s = str(val).strip()
    if re.match(r"^\d+\.\d{1,2}\$", s):
        v = int(round(float(s)))
        if allow_thousands_scale and 0 < v < 500:
            return v * 1000
        return v
    digits = re.sub(r"[^\d]", "", s)
    v = int(digits) if digits else 0
    if allow_thousands_scale and 0 < v < 500:
        return v * 1000
    return v

def get_col_value(lower_map: dict, candidate_keys: list, default=None):
    for key in candidate_keys:
        for col_k, col_v in lower_map.items():
            if key == col_k or key in col_k:
                if str(col_v).strip() not in ("", "0", "nan", "None", "NaT"):
                    return col_v
    return default

def normalize_records(raw_records: list) -> list:
    normalized = []
    id_keys = ["id", "product_id", "ma_sp", "mã sp", "ma sp", "mã hàng", "ma hang"]
    name_keys = [
        "product_name", "ten_sp", "tên sp", "ten sp",
        "tên sản phẩm", "ten san pham", "san_pham", "sản phẩm", "san pham",
        "tên hàng", "ten hang", "mặt hàng", "mat hang", "item_name", "name"
    ]
    orig_keys = [
        "original_price", "gia_goc", "giá gốc", "gia goc",
        "niêm yết", "niem yet", "giá bán lẻ", "giá thường", "giá cũ", "price"
    ]
    sale_keys = [
        "sale_price", "promo_price", "gia_km", "giá khuyến mãi", "gia khuyen mai",
        "giá km", "gia km", "ưu đãi", "uu dai", "giá giảm", "sau giảm", "discount_price"
    ]
    win_keys = [
        "win_member_price", "win_price", "gia_win", "giá hội viên", "gia hoi vien",
        "giá win", "gia win", "thẻ win", "the win", "member"
    ]

    for idx, row in enumerate(raw_records, start=1):
        lower_map = {str(k).strip().lower(): v for k, v in row.items()}

        prod_id = get_col_value(lower_map, id_keys, f"WM-{len(normalized)+1:03d}")
        prod_name = get_col_value(lower_map, name_keys, "")

        if not prod_name or str(prod_name).strip().isdigit():
            text_candidates = [
                str(v).strip() for k, v in row.items()
                if isinstance(v, str)
                and len(str(v).strip()) >= 6
                and not str(v).strip().isdigit()
                and not re.match(r"^(WM|SP)[-_]?\d+\$", str(v).strip(), re.I)
            ]
            if text_candidates:
                prod_name = max(text_candidates, key=len)

        orig_price = parse_price(get_col_value(lower_map, orig_keys, 0))
        sale_price = parse_price(get_col_value(lower_map, sale_keys, 0))
        win_price = parse_price(get_col_value(lower_map, win_keys, 0))

        if orig_price == 0 and sale_price == 0 and win_price == 0:
            numeric_prices = []
            for k, v in row.items():
                k_low = str(k).strip().lower()
                if any(skip in k_low for skip in ["stt", "id", "mã", "ma ", "%", "tiết kiệm", "tiet kiem", "giảm %"]):
                    continue
                p_val = parse_price(v, allow_thousands_scale=False)
                if p_val >= 1000:
                    numeric_prices.append(p_val)
            if numeric_prices:
                numeric_prices.sort(reverse=True)
                orig_price = numeric_prices[0]
                sale_price = numeric_prices[1] if len(numeric_prices) >= 2 else orig_price
                win_price = numeric_prices[2] if len(numeric_prices) >= 3 else sale_price

        if orig_price == 0 and sale_price > 0:
            orig_price = sale_price
        if sale_price == 0:
            sale_price = orig_price
        if win_price == 0:
            win_price = sale_price

        prices_sorted = sorted([orig_price, sale_price, win_price], reverse=True)
        orig_price, sale_price, win_price = prices_sorted[0], prices_sorted[1], prices_sorted[2]

        clean_name = str(prod_name).strip()
        if clean_name and clean_name.lower() not in ("nan", "none", "0") and orig_price >= 1000:
            normalized.append({
                "id": str(prod_id).strip(),
                "product_name": clean_name,
                "original_price": orig_price,
                "sale_price": sale_price,
                "win_member_price": win_price,
            })
    return normalized

def smart_load_tabular(file_path: str) -> list:
    if file_path.lower().endswith(".csv"):
        try:
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(file_path, encoding="latin1")
    else:
        df = pd.read_excel(file_path)

    for i in range(min(6, len(df))):
        row_text = " ".join([str(v).strip().lower() for v in df.iloc[i].values if pd.notna(v)])
        if any(k in row_text for k in ["tên", "ten", "sản phẩm", "san pham", "giá", "gia", "product", "price"]):
            df.columns = [str(v).strip() for v in df.iloc[i].values]
            df = df.iloc[i + 1:].reset_index(drop=True)
            break

    df = df.dropna(how="all").fillna(0)
    return normalize_records(df.to_dict(orient="records"))

def load_promotions():
    json_path = os.path.join(BASE_DIR, "promotions.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and any(int(item.get("original_price", 0)) >= 1000 for item in data):
                    return normalize_records(data)
        except Exception:
            pass

    for fname in os.listdir(BASE_DIR):
        if fname.startswith("~\$"):
            continue
        if fname.lower().endswith((".xlsx", ".xls", ".csv")):
            full_path = os.path.join(BASE_DIR, fname)
            records = smart_load_tabular(full_path)
            if records:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
                return records
    return []

# ==============================================================================
# 3. XỬ LÝ NGÔN NGỮ TỰ NHIÊN & THUẬT TOÁN TỐI ƯU
# ==============================================================================
ABBREVIATIONS = {
    "n giat": "nuoc giat",
    "nc giat": "nuoc giat",
    "nc mam": "nuoc mam",
    "nc rua chen": "nuoc rua chen",
    "nc rua bat": "nuoc rua chen",
    "nc lau san": "nuoc lau san",
    "nc tuong": "nuoc tuong",
    "sua tuoi": "sua tuoi",
    "dau an": "dau an",
    "bot giat": "nuoc giat",
    "kem danh rang": "kem danh rang"
}

def normalize_query_text(text: str) -> str:
    norm = remove_accents(text)
    for abbr, full in ABBREVIATIONS.items():
        norm = re.sub(rf"\b{re.escape(abbr)}\b", full, norm)
    return norm

def parse_with_regex(user_query: str):
    cleaned = normalize_query_text(user_query)
    parts = re.split(r",|\bvà\b|\bva\b|\bvoi\b|\bvới\b|\+|\n", cleaned)
    stop_words = [
        "mua", "lay cho tui", "lay cho minh", "lay", "tim", "check gia",
        "tu van", "giup minh", "giup tui", "cho minh", "cho tui", "toi muon",
        "cai", "tui", "hop", "chai", "loc", "thung", "goi", "kg", "lit", "l"
    ]
    items = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        qty_match = re.search(r"\b(\d+)\s*(kg|g|l|lit|chai|tui|hop|loc|thung|goi|cai)?\b", part)
        quantity = int(qty_match.group(1)) if qty_match else 1

        item_name = re.sub(r"\b\d+\s*(kg|g|l|lit|chai|tui|hop|loc|thung|goi|cai)?\b", " ", part)
        for sw in stop_words:
            item_name = re.sub(rf"\b{re.escape(sw)}\b", " ", item_name)
        item_name = re.sub(r"\s+", " ", item_name).strip()

        if len(item_name) >= 2:
            items.append({"item_name": item_name, "quantity": max(1, quantity)})
    return items

def parse_user_intent(user_query: str, api_key