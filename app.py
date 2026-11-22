import streamlit as st
import pandas as pd
import json
import os
import re
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
    /* Banner đầu trang chuẩn nhận diện WinMart */
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
    /* Thẻ tổng kết hóa đơn nổi bật */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(215, 25, 32, 0.35);
        padding: 14px 18px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    }
    /* Nút bấm chính màu đỏ WinMart */
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
    /* Nút gợi ý giỏ hàng bo tròn mềm mại */
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
    if re.match(r"^\d+\.\d{1,2}$", s):
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
                and not re.match(r"^(WM|SP)[-_]?\d+$", str(v).strip(), re.I)
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
        if fname.startswith("~$"):
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

def parse_user_intent(user_query: str, api_key: str):
    if api_key and api_key.strip():
        try:
            genai.configure(api_key=api_key.strip())
            prompt = f"""
            Bạn là trợ lý mua sắm của siêu thị WinMart. Trích xuất danh sách sản phẩm và số lượng từ câu sau.
            Giải mã từ viết tắt tiếng Việt (vd: 'n giat' -> 'nước giặt', 'nc mam' -> 'nước mắm', 'nc rua chen' -> 'nước rửa chén').
            Mặc định quantity = 1 nếu không nêu rõ.
            Trả về đúng định dạng JSON mảng: [{{"item_name": "tên sản phẩm", "quantity": số_nguyên}}]
            Câu yêu cầu: "{user_query}"
            """
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    response = model.generate_content(prompt)
                    parsed = json.loads(response.text)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        return parsed, f"Gemini AI ({model_name})"
                except Exception:
                    continue
        except Exception:
            pass
    return parse_with_regex(user_query), "Bộ xử lý cục bộ tốc độ cao"

def match_product(item_name: str, catalog: list):
    q_norm = normalize_query_text(item_name)
    q_tokens = set(q_norm.split())
    if not q_tokens:
        return None

    best_product = None
    best_score = 0.0

    for prod in catalog:
        p_name = str(prod.get("product_name", ""))
        p_norm = remove_accents(p_name)
        p_tokens = set(p_norm.split())

        score = 0.0
        if q_norm in p_norm:
            score += 2.5

        overlap = q_tokens.intersection(p_tokens)
        if overlap:
            score += (len(overlap) / len(q_tokens)) * 2.0
            for tok in overlap:
                if len(tok) >= 4:
                    score += 0.6

        if score > best_score:
            best_score = score
            best_product = prod

    if best_score >= 1.8:
        return best_product
    return None

def optimize_basket_knapsack(catalog: list, budget: int, is_win_member: bool):
    candidates = []
    for p in catalog:
        orig = int(p["original_price"])
        final = int(p["win_member_price"]) if (is_win_member and p["win_member_price"] < p["sale_price"]) else int(p["sale_price"])
        saving = max(0, orig - final)
        if 0 < final <= budget and saving > 0:
            candidates.append({
                **p,
                "final_price": final,
                "saving": saving,
                "weight": max(1, final // 1000)
            })

    W = budget // 1000
    n = len(candidates)
    if n == 0 or W <= 0:
        return []

    dp = [[0.0] * (W + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        w_i = candidates[i - 1]["weight"]
        v_i = candidates[i - 1]["saving"] + 0.001 * candidates[i - 1]["final_price"]
        for w in range(W + 1):
            dp[i][w] = dp[i - 1][w]
            if w_i <= w and dp[i - 1][w - w_i] + v_i > dp[i][w]:
                dp[i][w] = dp[i - 1][w - w_i] + v_i

    selected = []
    w = W
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            item = candidates[i - 1]
            selected.append(item)
            w -= item["weight"]

    return selected[::-1]

# ==============================================================================
# 4. GIAO DIỆN NGƯỜI DÙNG CHÍNH (CUSTOMER-FACING UI)
# ==============================================================================
catalog = load_promotions()

with st.sidebar:
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #D71920 0%, #9E0B10 100%);
                    padding: 16px; border-radius: 12px; margin-bottom: 16px; text-align: center;
                    border: 1px solid rgba(255, 210, 0, 0.4);">
            <span style="color: #FFD200; font-weight: 900; font-size: 26px; letter-spacing: 0.5px;">WinMart</span>
            <span style="color: #FFFFFF; font-weight: 600; font-size: 13px; display: block; margin-top: 2px;">
                TRỢ LÝ SĂN DEAL & MUA SẮM
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("### 💳 Quyền lợi Hội viên")
    is_win_member = st.toggle("Áp dụng thẻ Hội viên WiN", value=True, help="Bật để hưởng ưu đãi giảm giá độc quyền dành cho Hội viên WiN.")
    if is_win_member:
        st.success("✨ **Đang áp dụng giá Hội viên WiN** (Tiết kiệm tối đa)")
    else:
        st.warning("🏷️ **Đang áp dụng giá Khuyến mãi tuần** (Khách thường)")

    st.divider()
    st.markdown("### 🏪 Thông tin Cửa hàng")
    st.caption(f"🟢 Trạng thái hệ thống: **Sẵn sàng**")
    st.caption(f"📦 Danh mục ưu đãi tuần này: **{len(catalog)} sản phẩm**")
    st.caption("📍 Áp dụng toàn hệ thống WinMart / WinMart+")

    st.divider()
    with st.expander("⚙️ Cài đặt nâng cao (AI Engine)"):
        api_key = st.text_input(
            "Gemini API Key (Tùy chọn)",
            type="password",
            placeholder="Nhập khóa nếu muốn dùng Gemini Cloud...",
            help="Có thể để trống. Hệ thống tích hợp sẵn bộ phân tích ngôn ngữ cục bộ hoạt động ngay cả khi không có API Key."
        )
        if api_key.strip():
            st.caption("☁️ Chế độ: **Gemini Flash Cloud**")
        else:
            st.caption("⚡ Chế độ: **Local Smart Parser (Không cần Key)**")

# Banner chào mừng phía trên cùng
st.markdown(
    """
    <div class="winmart-hero">
        <h1>🛒 <span class="brand-gold">WinMart</span> Smart Shopper Assistant</h1>
        <p>Nhập danh sách đi chợ bằng ngôn ngữ tự nhiên — Tự động săn deal tốt nhất & tính hóa đơn tiết kiệm tức thì.</p>
    </div>
    """,
    unsafe_allow_html=True
)

if not catalog:
    st.error(f"⚠️ Không tìm thấy dữ liệu sản phẩm trong thư mục `{BASE_DIR}`.")
    st.stop()

if "shopping_input" not in st.session_state:
    st.session_state.shopping_input = "Mua 1kg thịt ba rọi, 1 túi n giat ariel, 1 lốc sữa TH và 1 chai nước mắm"

tab1, tab2, tab3 = st.tabs([
    "🛍️ Lên Giỏ Hàng & Tính Tiền",
    "🎯 Gợi Ý Giỏ Hàng Theo Ngân Sách",
    "🏷️ Bảng Giá Khuyến Mãi Tuần Này"
])

# ------------------------------------------------------------------------------
# TAB 1: TRỢ LÝ MUA SẮM DÀNH CHO KHÁCH HÀNG
# ------------------------------------------------------------------------------
with tab1:
    st.caption("💡 **Gợi ý đi chợ nhanh:** Chọn nhanh một giỏ hàng mẫu hoặc tự nhập danh sách của bạn bên dưới")
    gcol1, gcol2, gcol3 = st.columns(3)
    if gcol1.button("🥩 Bữa cơm gia đình", use_container_width=True):
        st.session_state.shopping_input = "Mua 1kg thịt ba rọi, 1 túi n giat ariel, 1 lốc sữa TH và 1 chai nước mắm"
    if gcol2.button("🌾 Đi chợ cuối tuần", use_container_width=True):
        st.session_state.shopping_input = "lay cho tui 2 goi gao st25, 1 dau an tuong an voi 2 chai nc rua chen sunlight"
    if gcol3.button("🍳 Đồ bếp thiết yếu", use_container_width=True):
        st.session_state.shopping_input = "Mua 1 chai dầu ăn Meizan, 2 hộp sữa chua và 1 túi nước giặt OMO"

    user_query = st.text_area(
        "📝 Bạn cần mua gì hôm nay? (Hỗ trợ gõ tự nhiên, không dấu hoặc viết tắt):",
        value=st.session_state.shopping_input,
        height=95,
        placeholder="Ví dụ: Mua 2kg gạo ST25, 1 chai dầu ăn, 1 lốc sữa tươi TH..."
    )

    if st.button("✨ Tính Hóa Đơn & Săn Deal Tốt Nhất", type="primary"):
        if not user_query.strip():
            st.warning("Bạn vui lòng nhập ít nhất 1 sản phẩm cần mua nhé!")
        else:
            with st.spinner("Đang tìm sản phẩm và áp dụng ưu đãi tốt nhất cho bạn..."):
                parsed_items, _ = parse_user_intent(user_query, api_key)

            invoice_rows = []
            chart_rows = []
            not_found_items = []
            total_orig = 0
            total_final = 0

            for entry in parsed_items:
                raw_name = entry.get("item_name", "")
                qty = max(1, int(entry.get("quantity", 1)))
                matched = match_product(raw_name, catalog)

                if matched:
                    orig_price = int(matched["original_price"])
                    sale_price = int(matched["sale_price"])
                    win_price = int(matched["win_member_price"])

                    if is_win_member and win_price < sale_price:
                        unit_final = win_price
                        promo_label = "💳 Ưu đãi Hội viên WiN"
                    else:
                        unit_final = sale_price
                        promo_label = "🏷️ Khuyến mãi tuần"

                    line_orig = orig_price * qty
                    line_final = unit_final * qty
                    line_saved = line_orig - line_final

                    total_orig += line_orig
                    total_final += line_final

                    invoice_rows.append({
                        "Mã SP": matched.get("id", "WM-SP"),
                        "Sản phẩm WinMart": matched["product_name"],
                        "SL": qty,
                        "Giá niêm yết": f"{line_orig:,.0f} đ",
                        "Giá ưu đãi": f"{line_final:,.0f} đ",
                        "Tiết kiệm": f"{line_saved:,.0f} đ",
                        "Chương trình áp dụng": promo_label
                    })
                    chart_rows.append({
                        "Sản phẩm": matched["product_name"][:24],
                        "Giá niêm yết (VNĐ)": line_orig,
                        "Giá thanh toán (VNĐ)": line_final
                    })
                else:
                    not_found_items.append(raw_name)

            if invoice_rows:
                st.markdown("### 🧾 Chi Tiết Hóa Đơn Của Bạn")
                df_invoice = pd.DataFrame(invoice_rows)
                st.dataframe(df_invoice, use_container_width=True, hide_index=True)

                total_saved = total_orig - total_final
                save_pct = (total_saved / total_orig * 100) if total_orig > 0 else 0

                col1, col2, col3 = st.columns(3)
                col1.metric("💰 Tổng giá gốc", f"{total_orig:,.0f} VNĐ")
                col2.metric("✅ Tổng thanh toán", f"{total_final:,.0f} VNĐ", delta=f"-{total_saved:,.0f} VNĐ")
                col3.metric("🎉 Bạn đã tiết kiệm", f"{total_saved:,.0f} VNĐ", delta=f"Giảm {save_pct:.1f}%")

                with st.expander("📊 Xem biểu đồ so sánh giá trước & sau ưu đãi", expanded=True):
                    df_chart = pd.DataFrame(chart_rows).set_index("Sản phẩm")
                    st.bar_chart(df_chart)

                csv_bytes = df_invoice.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    label="📥 Lưu hóa đơn về máy (.CSV)",
                    data=csv_bytes,
                    file_name="hoa_don_winmart.csv",
                    mime="text/csv"
                )

            if not_found_items:
                st.info(
                    f"ℹ️ **Lưu ý từ WinMart:** Các mặt hàng sau hiện chưa nằm trong chương trình khuyến mãi tuần này "
                    f"nên chưa được cộng vào hóa đơn: **{', '.join(not_found_items)}**."
                )

# ------------------------------------------------------------------------------
# TAB 2: GỢI Ý GIỎ HÀNG TỐI ƯU THEO NGÂN SÁCH (KNAPSACK)
# ------------------------------------------------------------------------------
with tab2:
    st.subheader("🎯 Tự Động Săn Deal Tối Đa Hóa Tiền Tiết Kiệm")
    st.write("Nhập số tiền bạn dự định chi tiêu, trợ lý thông minh sẽ chọn ra tổ hợp sản phẩm khuyến mãi **hời nhất** trong tầm giá.")

    budget_input = st.number_input(
        "💵 Ngân sách đi siêu thị của bạn (VNĐ):",
        min_value=50000,
        max_value=5000000,
        value=300000,
        step=50000
    )

    if st.button("🚀 Tìm giỏ hàng tiết kiệm nhất", type="primary"):
        optimal_items = optimize_basket_knapsack(catalog, int(budget_input), is_win_member)
        if optimal_items:
            opt_rows = []
            sum_orig = 0
            sum_pay = 0
            for item in optimal_items:
                sum_orig += item["original_price"]
                sum_pay += item["final_price"]
                opt_rows.append({
                    "Mã SP": item["id"],
                    "Sản phẩm đề xuất": item["product_name"],
                    "Giá niêm yết": f"{item['original_price']:,.0f} đ",
                    "Giá ưu đãi": f"{item['final_price']:,.0f} đ",
                    "Tiết kiệm được": f"{item['saving']:,.0f} đ"
                })
            st.dataframe(pd.DataFrame(opt_rows), use_container_width=True, hide_index=True)
            k1, k2, k3 = st.columns(3)
            k1.metric("💵 Ngân sách tối đa", f"{budget_input:,.0f} VNĐ")
            k2.metric("🛒 Tổng thanh toán", f"{sum_pay:,.0f} VNĐ", delta=f"Còn dư {budget_input - sum_pay:,.0f} VNĐ")
            k3.metric("🏆 Tổng tiền tiết kiệm", f"{sum_orig - sum_pay:,.0f} VNĐ", delta=f"Giảm {(sum_orig - sum_pay)/sum_orig*100:.1f}%")
        else:
            st.warning("Chưa tìm thấy tổ hợp sản phẩm phù hợp với mức ngân sách này.")

# ------------------------------------------------------------------------------
# TAB 3: TRA CỨU BẢNG GIÁ KHUYẾN MÃI
# ------------------------------------------------------------------------------
with tab3:
    st.subheader("🏷️ Danh Mục Sản Phẩm Đang Khuyến Mãi Tại WinMart")
    search_kw = st.text_input("🔎 Tìm kiếm sản phẩm:", placeholder="Gõ tên sản phẩm hoặc thương hiệu (vd: Ariel, sữa TH, gạo ST25...)")
    df_cat = pd.DataFrame(catalog)
    if search_kw.strip():
        kw_norm = remove_accents(search_kw)
        df_cat = df_cat[df_cat["product_name"].apply(lambda x: kw_norm in remove_accents(x))]

    df_display = df_cat[["id", "product_name", "original_price", "sale_price", "win_member_price"]].copy()
    df_display.columns = ["Mã SP", "Tên sản phẩm", "Giá niêm yết (VNĐ)", "Khuyến mãi tuần (VNĐ)", "Giá Hội viên WiN (VNĐ)"]
    st.dataframe(df_display, use_container_width=True, hide_index=True, height=430)