import os
import re
import json
import math
import unicodedata
import urllib.parse
import pandas as pd
import streamlit as st

# ==============================================================================
# CẤU HÌNH TRANG & GIAO DIỆN THƯƠNG HIỆU WINMART (ĐỎ - VÀNG)
# ==============================================================================
st.set_page_config(
    page_title="WinMart Smart Shopper Agent",
    page_icon="🛒",
    layout="wide"
)

st.markdown("""
<style>
    .winmart-banner {
        background: linear-gradient(90deg, #D71920 0%, #B71218 100%);
        padding: 18px 24px;
        border-radius: 12px;
        color: white;
        margin-bottom: 18px;
        border-bottom: 4px solid #FFD100;
    }
    .winmart-banner h1 {
        color: #FFFFFF;
        margin: 0;
        font-size: 26px;
    }
    .winmart-banner p {
        color: #FFF3CD;
        margin: 6px 0 0 0;
        font-size: 14px;
    }
</style>
<div class="winmart-banner">
    <h1>🛒 WINMART SMART SHOPPER AGENT</h1>
    <p>Trợ lý Mua sắm Thông minh & Săn Deal Tiết Kiệm • Tích hợp Ưu đãi Hội viên WiN</p>
</div>
""", unsafe_allow_html=True)

# ==============================================================================
# MODULE 1: NẠP VÀ CHUẨN HÓA CƠ SỞ DỮ LIỆU KHUYẾN MÃI (105 SẢN PHẨM)
# ==============================================================================
def smart_load_tabular(filepath):
    raw_df = pd.read_excel(filepath, header=None)
    header_row = 0
    for idx in range(min(6, len(raw_df))):
        row_str = " ".join(str(x).lower() for x in raw_df.iloc[idx].tolist())
        if any(k in row_str for k in ["tên", "sản phẩm", "product", "giá", "price"]):
            header_row = idx
            break

    df = pd.read_excel(filepath, header=header_row)
    catalog = []
    for idx, row in df.iterrows():
        name = ""
        prices = []
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                continue
            s_val = str(val).strip()
            # Tìm tên sản phẩm (chuỗi chữ có độ dài >= 4)
            if not name and re.search(r"[a-zA-ZÀ-ỹ]{3,}", s_val) and not s_val.replace(".", "").isdigit():
                name = s_val
            # Tìm các cột giá tiền >= 1000 VNĐ
            num_str = re.sub(r"[^\d]", "", s_val)
            if num_str:
                num = int(num_str)
                if 1000 <= num <= 50_000_000:
                    prices.append(num)

        if name and prices:
            prices_sorted = sorted(list(set(prices)), reverse=True)
            orig = prices_sorted[0]
            sale = prices_sorted[1] if len(prices_sorted) >= 2 else orig
            win = prices_sorted[2] if len(prices_sorted) >= 3 else sale
            catalog.append({
                "id": f"WM-{idx + 1:03d}",
                "product_name": name,
                "original_price": orig,
                "sale_price": sale,
                "win_member_price": win
            })
    return catalog


@st.cache_data
def load_promotions():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "promotions.json")
    xlsx_path = os.path.join(base_dir, "winmart_promotions_105.xlsx")

    catalog = []
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                # Kiểm tra xem có bị lỗi giá 0đ không
                if any(int(item.get("original_price", 0)) > 0 for item in data):
                    catalog = data
        except Exception:
            catalog = []

    if not catalog and os.path.exists(xlsx_path):
        catalog = smart_load_tabular(xlsx_path)
        if catalog:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, ensure_ascii=False, indent=2)

    # Chuẩn hóa bất biến logic giá: Giá niêm yết >= Giá KM tuần >= Giá Hội viên WiN > 0
    cleaned_catalog = []
    for i, item in enumerate(catalog):
        orig = int(item.get("original_price", 0))
        sale = int(item.get("sale_price", orig))
        win = int(item.get("win_member_price", sale))
        if orig <= 0:
            continue
        if sale <= 0 or sale > orig:
            sale = orig
        if win <= 0 or win > sale:
            win = sale
        cleaned_catalog.append({
            "id": item.get("id", f"WM-{i + 1:03d}"),
            "product_name": str(item.get("product_name", "")).strip(),
            "original_price": orig,
            "sale_price": sale,
            "win_member_price": win
        })
    return cleaned_catalog


# ==============================================================================
# MODULE 2: CHUẨN HÓA NGÔN NGỮ & BÓC TÁCH Ý ĐỊNH (GEMINI FLASH + OFFLINE REGEX)
# ==============================================================================
ABBREVIATIONS = {
    "n giat": "nuoc giat",
    "nc giat": "nuoc giat",
    "bot giat": "nuoc giat",
    "nc mam": "nuoc mam",
    "n mam": "nuoc mam",
    "nc rua chen": "nuoc rua chen",
    "nc rua bat": "nuoc rua chen",
    "n rua chen": "nuoc rua chen",
    "dau goi": "dau goi",
    "sua tuoi": "sua tuoi",
    "sua chua": "sua chua",
    "dau an": "dau an",
    "mi tom": "mi an lien",
    "mi goi": "mi an lien",
    "kem danh rang": "kem danh rang",
    "kdr": "kem danh rang"
}

STOP_WORDS = {
    "mua", "lay", "cho", "tui", "toi", "minh", "em", "anh", "chi", "giup",
    "can", "tim", "xem", "gia", "tinh", "tien", "hoa", "don", "di", "nhe", "a", "voi"
}

UNITS = r"(?:goi|chai|tui|hop|loc|thung|kg|g|lit|l|cai|chiec|lon|hu|bich|vỉ|vi|qua|trai|bo)"


def remove_accents(text):
    if not text:
        return ""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", text)
    no_accent = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return no_accent.lower().strip()


def normalize_query_text(text):
    norm = remove_accents(text)
    norm = re.sub(r"[^\w\s,\.+]", " ", norm)
    for abbr, full in ABBREVIATIONS.items():
        norm = re.sub(rf"\b{re.escape(abbr)}\b", full, norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def parse_with_regex(query_text):
    norm = normalize_query_text(query_text)
    segments = re.split(r"[,;\+]|\bva\b|\bvoi\b", norm)
    results = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # Tìm số lượng ở đầu cụm (VD: "2 goi gao st25" hoặc "2gao st25")
        qty = 1
        m = re.match(rf"^(\d+)\s*(?:{UNITS}\b)?\s*(.+)$", seg)
        if m:
            qty = max(1, int(m.group(1)))
            item_part = m.group(2)
        else:
            item_part = re.sub(rf"^(?:{UNITS})\b\s*", "", seg)

        # Loại bỏ từ dừng giao tiếp thừa
        tokens = [t for t in item_part.split() if t not in STOP_WORDS]
        clean_name = " ".join(tokens).strip()
        if clean_name:
            results.append({"item_name": clean_name, "quantity": qty})
    return results


def parse_user_intent(query_text, api_key=""):
    if api_key and api_key.strip():
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key.strip())
            model = genai.GenerativeModel(
                "gemini-2.5-flash",
                generation_config={"response_mime_type": "application/json"}
            )
            prompt = (
                "Bạn là hệ thống trích xuất thực thể mua sắm siêu thị WinMart. "
                "Hãy bóc tách danh sách sản phẩm và số lượng từ câu tiếng Việt sau "
                "(tự giải mã từ viết tắt như nc rua chen -> nước rửa chén, n giat -> nước giặt). "
                'Trả về duy nhất mảng JSON dạng [{"item_name": "tên sản phẩm", "quantity": 1}]. '
                f"Câu khách hàng: {query_text}"
            )
            response = model.generate_content(prompt)
            data = json.loads(response.text)
            if isinstance(data, list) and len(data) > 0:
                cleaned = []
                for entry in data:
                    if isinstance(entry, dict) and entry.get("item_name"):
                        try:
                            qty = max(1, int(float(entry.get("quantity", 1))))
                        except (ValueError, TypeError):
                            qty = 1
                        cleaned.append({
                            "item_name": str(entry["item_name"]).strip(),
                            "quantity": qty
                        })
                if cleaned:
                    return cleaned, "Gemini 2.5 Flash AI (Online)"
        except Exception:
            pass  # Tự động chuyển sang bộ lọc dự phòng Offline nếu sai key hoặc lỗi mạng

    return parse_with_regex(query_text), "Bộ lọc quy tắc cục bộ (Offline)"


# ==============================================================================
# MODULE 3: KHỚP MÃ SẢN PHẨM & CHỐT CHẶN CHỐNG ẢO GIÁC NGOÀI DANH MỤC
# ==============================================================================
def match_product(query_item, catalog, threshold=1.8):
    q_norm = normalize_query_text(query_item)
    q_tokens = set(q_norm.split())
    if not q_tokens:
        return None

    best_item = None
    best_score = 0.0

    for item in catalog:
        p_norm = remove_accents(item["product_name"])
        p_tokens = set(p_norm.split())

        in_substr = 1.0 if q_norm in p_norm else 0.0
        common_tokens = q_tokens.intersection(p_tokens)
        overlap_ratio = len(common_tokens) / len(q_tokens)
        long_token_bonus = sum(0.6 for t in common_tokens if len(t) >= 4)

        score = 2.5 * in_substr + 2.0 * overlap_ratio + long_token_bonus
        if score > best_score:
            best_score = score
            best_item = item

    if best_score >= threshold:
        return best_item
    return None


# ==============================================================================
# MODULE 4: THUẬT TOÁN QUY HOẠCH ĐỘNG 0/1 KNAPSACK TỐI ƯU GIỎ HÀNG THEO NGÂN SÁCH
# ==============================================================================
def optimize_basket_knapsack(catalog, budget, is_win_member=True):
    if not catalog or budget <= 0:
        return []

    step = 100  # Chuẩn hóa bước 100đ để giữ chính xác giá lẻ siêu thị (19.900đ, 45.500đ)
    W = int(budget // step)
    if W <= 0:
        return []

    valid_items = []
    for item in catalog:
        orig = int(item["original_price"])
        sale = int(item["sale_price"])
        win = int(item["win_member_price"])
        final = win if (is_win_member and win < sale) else sale
        saving = max(0, orig - final)
        weight = math.ceil(final / step)

        if 0 < final <= budget and weight <= W:
            value = saving + 0.001 * final
            valid_items.append((item, final, saving, weight, value))

    n = len(valid_items)
    if n == 0:
        return []

    dp = [0.0] * (W + 1)
    keep = [[False] * (W + 1) for _ in range(n)]

    for i in range(n):
        _, _, _, w, v = valid_items[i]
        for cap in range(W, w - 1, -1):
            if dp[cap - w] + v > dp[cap]:
                dp[cap] = dp[cap - w] + v
                keep[i][cap] = True

    best_cap = max(range(W + 1), key=lambda c: dp[c])
    selected = []
    curr_cap = best_cap
    for i in range(n - 1, -1, -1):
        if keep[i][curr_cap]:
            item, final, saving, w, _ = valid_items[i]
            promo_label = (
                "Ưu đãi Hội viên WiN"
                if (is_win_member and item["win_member_price"] == final and final < item["sale_price"])
                else ("Khuyến mãi tuần" if final < item["original_price"] else "Giá niêm yết")
            )
            selected.append({
                "Mã SKU": item["id"],
                "Tên sản phẩm": item["product_name"],
                "Chương trình": promo_label,
                "Giá niêm yết (đ)": item["original_price"],
                "Giá ưu đãi (đ)": final,
                "Tiết kiệm (đ)": saving,
                "Link mua hàng": f"https://winmart.vn/search?q={urllib.parse.quote(item['product_name'])}"
            })
            curr_cap -= w

    selected.reverse()
    return selected


# ==============================================================================
# GIAO DIỆN CHÍNH & THANH ĐIỀU HƯỚNG BÊN TRÁI
# ==============================================================================
catalog = load_promotions()

with st.sidebar:
    st.header("⚙️ Thiết lập Mua sắm")
    is_win_member = st.toggle("💳 Áp dụng thẻ Hội viên WiN", value=True)
    if is_win_member:
        st.success("Đang bật giá độc quyền Hội viên WiN!")
    else:
        st.info("Đang tính theo giá khuyến mãi thường.")

    st.divider()
    with st.expander("🔑 Cấu hình Gemini API (Tùy chọn)"):
        api_key = st.text_input(
            "Nhập GEMINI_API_KEY:",
            type="password",
            placeholder="AIzaSy...",
            help="Không bắt buộc. Nếu bỏ trống hoặc sai key, hệ thống tự chạy bộ lọc cục bộ siêu tốc."
        )

    st.divider()
    st.caption(f"📦 Kho dữ liệu hiện có: **{len(catalog)}** mặt hàng WinMart.")

if not catalog:
    st.error("⚠️ Không tìm thấy tệp dữ liệu `promotions.json` hoặc `winmart_promotions_105.xlsx` trong cùng thư mục với `app.py`.")
    st.stop()

# ==============================================================================
# 3 PHÂN HỆ CHỨC NĂNG CHÍNH (TABS)
# ==============================================================================
tab1, tab2, tab3 = st.tabs([
    "🛍️ Lên Giỏ Hàng & Tính Tiền",
    "🎯 Gợi Ý Giỏ Hàng Theo Ngân Sách",
    "📋 Bảng Giá Khuyến Mãi Tuần Này"
])

# ------------------------------------------------------------------------------
# TAB 1: LÊN GIỎ HÀNG & TÍNH TIỀN TỰ ĐỘNG
# ------------------------------------------------------------------------------
with tab1:
    st.subheader("Nhập danh sách sản phẩm bạn cần mua bằng tiếng Việt tự nhiên")
    st.caption("Hỗ trợ cả câu không dấu, thiếu dấu phẩy và từ viết tắt (ví dụ: n giat, nc mam, nc rua chen...)")

    if "user_query" not in st.session_state:
        st.session_state["user_query"] = ""

    st.write("**💡 Gợi ý giỏ hàng nhanh (bấm để điền mẫu):**")
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        if st.button("🍚 Bữa cơm gia đình", use_container_width=True):
            st.session_state["user_query"] = "1 túi gạo ST25, 1 chai nước mắm Nam Ngư, 1 dầu ăn Tường An, 2 hộp sữa tươi Vinamilk"
            st.rerun()
    with col_b2:
        if st.button("🛒 Đi chợ cuối tuần (Không dấu)", use_container_width=True):
            st.session_state["user_query"] = "lay cho tui 2 goi gao st25, 1 dau an tuong an voi 2 chai nc rua chen sunlight"
            st.rerun()
    with col_b3:
        if st.button("🧴 Đồ bếp & Giặt giũ thiết yếu", use_container_width=True):
            st.session_state["user_query"] = "1 túi n giat Ariel, 2 chai nc rua chen, 1 kem danh rang Colgate"
            st.rerun()

    user_query = st.text_area(
        "Danh sách cần mua của bạn:",
        key="user_query",
        height=95,
        placeholder="Ví dụ: Mua cho mình 2 gói gạo ST25, 1 túi nước giặt Ariel và 2 chai nước rửa chén Sunlight..."
    )

    if st.button("🧾 Tính Hóa Đơn & Săn Deal Tốt Nhất", type="primary"):
        if not user_query or not user_query.strip():
            st.warning("⚠️ Bạn chưa nhập danh sách sản phẩm cần mua. Hãy gõ tên món hoặc bấm một nút gợi ý ở trên nhé!")
        else:
            parsed_entities, engine_used = parse_user_intent(user_query, api_key)
            if not parsed_entities:
                st.warning("⚠️ Hệ thống chưa nhận diện được tên sản phẩm nào từ câu nhập. Bạn thử viết rõ tên mặt hàng hơn nhé!")
            else:
                matched_rows = []
                not_found_items = []

                for ent in parsed_entities:
                    raw_name = ent["item_name"]
                    qty = ent["quantity"]
                    product = match_product(raw_name, catalog)

                    if product is None:
                        not_found_items.append(f"{raw_name} (SL: {qty})")
                    else:
                        orig = product["original_price"]
                        sale = product["sale_price"]
                        win = product["win_member_price"]
                        unit_final = win if (is_win_member and win < sale) else sale
                        promo_tag = (
                            "Ưu đãi Hội viên WiN"
                            if (is_win_member and win < sale)
                            else ("Khuyến mãi tuần" if sale < orig else "Giá niêm yết")
                        )
                        row_orig = orig * qty
                        row_final = unit_final * qty
                        row_save = max(0, row_orig - row_final)

                        matched_rows.append({
                            "Mã SKU": product["id"],
                            "Tên sản phẩm": product["product_name"],
                            "SL": qty,
                            "Chương trình": promo_tag,
                            "Đơn giá gốc (đ)": orig,
                            "Đơn giá ưu đãi (đ)": unit_final,
                            "Thành tiền (đ)": row_final,
                            "Tiết kiệm (đ)": row_save,
                            "Link mua hàng": f"https://winmart.vn/search?q={urllib.parse.quote(product['product_name'])}"
                        })

                st.caption(f"⚙️ Động cơ xử lý ngôn ngữ: **{engine_used}**")

                if not matched_rows:
                    st.warning("⚠️ Không có mặt hàng nào trong yêu cầu của bạn thuộc danh mục khuyến mãi tuần này.")
                else:
                    df_bill = pd.DataFrame(matched_rows)
                    total_orig = int(df_bill["Đơn giá gốc (đ)"].mul(df_bill["SL"]).sum())
                    total_pay = int(df_bill["Thành tiền (đ)"].sum())
                    total_save = max(0, total_orig - total_pay)
                    save_pct = (total_save / total_orig * 100) if total_orig > 0 else 0.0

                    st.markdown("### 📊 Bảng Chi Tiết Hóa Đơn Ưu Đãi")
                    st.dataframe(
                        df_bill,
                        column_config={
                            "Đơn giá gốc (đ)": st.column_config.NumberColumn(format="%d đ"),
                            "Đơn giá ưu đãi (đ)": st.column_config.NumberColumn(format="%d đ"),
                            "Thành tiền (đ)": st.column_config.NumberColumn(format="%d đ"),
                            "Tiết kiệm (đ)": st.column_config.NumberColumn(format="%d đ"),
                            "Link mua hàng": st.column_config.LinkColumn(
                                "Đặt mua",
                                help="Bấm để mở trang tìm sản phẩm trên WinMart.vn",
                                display_text="🛒 Mua ngay"
                            )
                        },
                        use_container_width=True,
                        hide_index=True
                    )

                    k1, k2, k3 = st.columns(3)
                    k1.metric("Tổng giá niêm yết gốc", f"{total_orig:,.0f} đ")
                    k2.metric("Tổng thanh toán ưu đãi", f"{total_pay:,.0f} đ", delta=f"-{save_pct:.1f}%")
                    k3.metric("🎉 Bạn đã tiết kiệm được", f"{total_save:,.0f} đ")

                    st.markdown("### 📈 Biểu Đồ So Sánh Chi Phí Trước & Sau Ưu Đãi")
                    chart_df = pd.DataFrame({
                        "Sản phẩm": df_bill["Tên sản phẩm"],
                        "Giá niêm yết gốc": df_bill["Đơn giá gốc (đ)"] * df_bill["SL"],
                        "Giá sau ưu đãi": df_bill["Thành tiền (đ)"]
                    }).set_index("Sản phẩm")
                    st.bar_chart(chart_df)

                    csv_bytes = df_bill.drop(columns=["Link mua hàng"]).to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        label="📥 Tải hóa đơn chi tiết (.CSV mở chuẩn trên Excel)",
                        data=csv_bytes,
                        file_name="hoa_don_winmart.csv",
                        mime="text/csv"
                    )

                if not_found_items:
                    st.info(
                        "ℹ️ **Cảnh báo minh bạch (Sản phẩm ngoài danh mục khuyến mãi):** "
                        f"Các mặt hàng sau hiện không có trong chương trình khuyến mãi tuần này nên hệ thống không tự ý cộng tiền vào hóa đơn: **{', '.join(not_found_items)}**."
                    )

# ------------------------------------------------------------------------------
# TAB 2: GỢI Ý GIỎ HÀNG TỐI ƯU THEO NGÂN SÁCH (THUẬT TOÁN 0/1 KNAPSACK)
# ------------------------------------------------------------------------------
with tab2:
    st.subheader("Tìm tổ hợp sản phẩm giảm giá sâu nhất trong giới hạn ngân sách")
    st.caption("Sử dụng thuật toán Quy hoạch động 0/1 Knapsack để tối đa hóa tổng số tiền tiết kiệm mà không vượt quá ngân sách.")

    budget = st.number_input(
        "Nhập ngân sách tối đa của bạn (VNĐ):",
        min_value=0,
        max_value=20_000_000,
        value=300_000,
        step=10_000
    )

    if st.button("🎯 Tìm giỏ hàng tiết kiệm nhất", type="primary"):
        if budget <= 0:
            st.warning("⚠️ Vui lòng nhập mức ngân sách lớn hơn **0 đ** để hệ thống tìm sản phẩm giúp bạn.")
        else:
            best_basket = optimize_basket_knapsack(catalog, budget, is_win_member)
            if not best_basket:
                all_prices = [
                    (item["win_member_price"] if (is_win_member and item["win_member_price"] < item["sale_price"]) else item["sale_price"])
                    for item in catalog
                ]
                min_price = min(all_prices) if all_prices else 0
                st.info(
                    f"ℹ️ Với ngân sách **{budget:,.0f} đ**, hiện **không có sản phẩm khuyến mãi nào** phù hợp trong danh mục tuần này. "
                    f"Sản phẩm ưu đãi có mức giá thấp nhất hiện tại là **{min_price:,.0f} đ** — bạn hãy thử tăng ngân sách lên từ mức này nhé!"
                )
            else:
                df_opt = pd.DataFrame(best_basket)
                opt_orig = int(df_opt["Giá niêm yết (đ)"].sum())
                opt_pay = int(df_opt["Giá ưu đãi (đ)"].sum())
                opt_save = int(df_opt["Tiết kiệm (đ)"].sum())
                remaining = int(budget - opt_pay)

                st.success(f"✅ Đã tìm thấy tổ hợp tối ưu gồm **{len(df_opt)} sản phẩm** trong ngân sách **{budget:,.0f} đ**!")
                st.dataframe(
                    df_opt,
                    column_config={
                        "Giá niêm yết (đ)": st.column_config.NumberColumn(format="%d đ"),
                        "Giá ưu đãi (đ)": st.column_config.NumberColumn(format="%d đ"),
                        "Tiết kiệm (đ)": st.column_config.NumberColumn(format="%d đ"),
                        "Link mua hàng": st.column_config.LinkColumn(
                            "Đặt mua",
                            help="Bấm để mở trang tìm sản phẩm trên WinMart.vn",
                            display_text="🛒 Mua ngay"
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )

                m1, m2, m3 = st.columns(3)
                m1.metric("Tổng thanh toán giỏ hàng", f"{opt_pay:,.0f} đ", delta=f"Dùng {opt_pay/budget*100:.1f}% ngân sách")
                m2.metric("🎉 Tổng tiền tiết kiệm", f"{opt_save:,.0f} đ")
                m3.metric("Ngân sách còn dư", f"{remaining:,.0f} đ")

# ------------------------------------------------------------------------------
# TAB 3: TRA CỨU BẢNG GIÁ KHUYẾN MÃI TUẦN NÀY
# ------------------------------------------------------------------------------
with tab3:
    st.subheader("Danh mục toàn bộ sản phẩm khuyến mãi WinMart tuần này")
    search_kw = st.text_input("🔍 Tìm kiếm nhanh theo tên sản phẩm hoặc thương hiệu:", placeholder="Ví dụ: Ariel, gạo, sữa, dầu ăn...")

    filtered = catalog
    if search_kw and search_kw.strip():
        kw_norm = remove_accents(search_kw)
        filtered = [item for item in catalog if kw_norm in remove_accents(item["product_name"])]

    if not filtered:
        st.info("Không tìm thấy sản phẩm nào khớp với từ khóa tìm kiếm.")
    else:
        df_cat = pd.DataFrame(filtered).rename(columns={
            "id": "Mã SKU",
            "product_name": "Tên sản phẩm",
            "original_price": "Giá niêm yết (đ)",
            "sale_price": "Khuyến mãi tuần (đ)",
            "win_member_price": "Giá Hội viên WiN (đ)"
        })
        st.dataframe(
            df_cat,
            column_config={
                "Giá niêm yết (đ)": st.column_config.NumberColumn(format="%d đ"),
                "Khuyến mãi tuần (đ)": st.column_config.NumberColumn(format="%d đ"),
                "Giá Hội viên WiN (đ)": st.column_config.NumberColumn(format="%d đ"),
            },
            use_container_width=True,
            hide_index=True
        )