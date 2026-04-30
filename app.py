import re
import time
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd
import requests
import streamlit as st
import tldextract
import whois


st.set_page_config(
    page_title="Guest Posting Site Analyzer",
    layout="wide"
)


# -----------------------------
# Styling
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: #f6f8fb;
    }

    .block-container {
        padding-top: 1.5rem;
        max-width: 1450px;
    }

    .main-title {
        font-size: 38px;
        font-weight: 850;
        color: #0f172a;
        margin-bottom: 4px;
    }

    .sub-title {
        color: #64748b;
        font-size: 15px;
        margin-bottom: 18px;
    }

    .info-box {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 16px 18px;
        margin-bottom: 18px;
        color: #334155;
    }

    .kpi-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 16px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
    }

    .kpi-label {
        color: #64748b;
        font-size: 13px;
        font-weight: 700;
    }

    .kpi-value {
        color: #0f172a;
        font-size: 30px;
        font-weight: 850;
        margin-top: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# -----------------------------
# Helper functions
# -----------------------------
def clean_domain(value: str) -> str:
    if value is None:
        return ""

    text = str(value).strip().lower()

    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/")[0]
    text = text.split("?")[0]
    text = text.split("#")[0]
    text = text.strip()

    ext = tldextract.extract(text)

    if not ext.domain or not ext.suffix:
        return text

    return f"{ext.domain}.{ext.suffix}"


def traffic_bucket(value) -> str:
    try:
        v = float(str(value).replace(",", "").strip())
    except Exception:
        return "Need Check"

    if v <= 0:
        return "Very Low"
    if v < 100:
        return "Very Low"
    if v < 500:
        return "Low"
    if v < 2000:
        return "Medium"
    if v < 10000:
        return "Good"
    return "High"


def safe_number(value, default=0.0):
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return default


def check_live_status(domain: str) -> dict:
    result = {
        "Live Status": "Unknown",
        "HTTPS": "No",
        "Final URL": "",
        "HTTP Code": "",
        "Title": "",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 Guest Posting Analyzer"
    }

    for scheme in ["https", "http"]:
        url = f"{scheme}://{domain}"

        try:
            r = requests.get(
                url,
                timeout=8,
                headers=headers,
                allow_redirects=True
            )

            result["HTTP Code"] = r.status_code
            result["Final URL"] = r.url

            if scheme == "https" or r.url.startswith("https://"):
                result["HTTPS"] = "Yes"

            if r.status_code < 400:
                result["Live Status"] = "Live"

                title_match = re.search(
                    r"<title[^>]*>(.*?)</title>",
                    r.text,
                    re.I | re.S
                )

                if title_match:
                    title = re.sub(r"\s+", " ", title_match.group(1)).strip()
                    result["Title"] = title[:120]

                return result

        except Exception:
            continue

    result["Live Status"] = "Dead / Blocked"
    return result


def get_domain_age(domain: str) -> dict:
    result = {
        "Creation Date": "",
        "Domain Age Years": "",
        "WHOIS Status": "Not Checked"
    }

    try:
        w = whois.whois(domain)
        creation_date = w.creation_date

        if isinstance(creation_date, list):
            creation_date = creation_date[0]

        if not creation_date:
            result["WHOIS Status"] = "Not Found"
            return result

        if creation_date.tzinfo is None:
            creation_date = creation_date.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age_years = (now - creation_date).days / 365.25

        result["Creation Date"] = creation_date.strftime("%Y-%m-%d")
        result["Domain Age Years"] = round(age_years, 2)
        result["WHOIS Status"] = "Found"

    except Exception:
        result["WHOIS Status"] = "Failed"

    return result


def google_index_link(domain: str) -> str:
    return f"https://www.google.com/search?q=site%3A{domain}"


def ahrefs_link(domain: str) -> str:
    return f"https://ahrefs.com/traffic-checker/?input={domain}"


def moz_link(domain: str) -> str:
    return f"https://moz.com/domain-analysis?site={domain}"


def score_site(row) -> tuple:
    score = 0
    reasons = []

    da = safe_number(row.get("DA", 0))
    pa = safe_number(row.get("PA", 0))
    spam = safe_number(row.get("Spam Score", 0))
    traffic = safe_number(row.get("Ahrefs Traffic", 0))
    age = safe_number(row.get("Domain Age Years", 0))
    indexed = safe_number(row.get("Indexed Pages", 0))
    price = safe_number(row.get("Price", 0))

    live = row.get("Live Status", "")
    https = row.get("HTTPS", "")

    if live == "Live":
        score += 15
        reasons.append("site live")
    else:
        score -= 30
        reasons.append("site not opening")

    if https == "Yes":
        score += 5
        reasons.append("https available")

    if da >= 40:
        score += 20
        reasons.append("DA strong")
    elif da >= 30:
        score += 15
        reasons.append("DA good")
    elif da >= 20:
        score += 8
        reasons.append("DA average")
    elif da > 0:
        score += 2
        reasons.append("DA low")
    else:
        reasons.append("DA missing")

    if pa >= 30:
        score += 8
        reasons.append("PA good")
    elif pa > 0:
        score += 3
        reasons.append("PA low/average")

    if spam == 0:
        reasons.append("spam missing")
    elif spam <= 3:
        score += 15
        reasons.append("spam low")
    elif spam <= 10:
        score += 5
        reasons.append("spam medium")
    else:
        score -= 25
        reasons.append("spam high")

    if traffic >= 10000:
        score += 25
        reasons.append("traffic high")
    elif traffic >= 2000:
        score += 20
        reasons.append("traffic good")
    elif traffic >= 500:
        score += 12
        reasons.append("traffic medium")
    elif traffic >= 100:
        score += 5
        reasons.append("traffic low")
    else:
        reasons.append("traffic missing/very low")

    if age >= 3:
        score += 15
        reasons.append("aged domain")
    elif age >= 1:
        score += 8
        reasons.append("domain age ok")
    elif age > 0:
        score -= 5
        reasons.append("new domain")
    else:
        reasons.append("domain age missing")

    if indexed >= 500:
        score += 12
        reasons.append("indexed pages strong")
    elif indexed >= 100:
        score += 8
        reasons.append("indexed pages ok")
    elif indexed >= 20:
        score += 3
        reasons.append("low indexed pages")
    elif indexed > 0:
        score -= 5
        reasons.append("very low indexed pages")
    else:
        reasons.append("index pages missing")

    if price > 0:
        if score >= 70 and price <= 1500:
            score += 8
            reasons.append("good value price")
        elif price > 5000 and score < 70:
            score -= 10
            reasons.append("price high vs quality")

    if score >= 75:
        decision = "Good"
    elif score >= 55:
        decision = "Average"
    elif score >= 35:
        decision = "Risky"
    else:
        decision = "Avoid"

    return score, decision, ", ".join(reasons)


def build_initial_df(domains):
    rows = []

    for raw in domains:
        domain = clean_domain(raw)

        if not domain:
            continue

        rows.append({
            "Input": raw,
            "Domain": domain,
            "DA": "",
            "PA": "",
            "Spam Score": "",
            "Ahrefs Traffic": "",
            "Indexed Pages": "",
            "Price": "",
            "Niche": "",
            "Contact": "",
            "Notes": "",
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df["Duplicate"] = df.duplicated(subset=["Domain"], keep=False).map(
        lambda x: "Yes" if x else "No"
    )

    df = df.drop_duplicates(subset=["Domain"], keep="first").reset_index(drop=True)

    return df


def to_excel(df):
    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Guest_Post_Analysis", index=False)

    return buffer.getvalue()


# -----------------------------
# Header
# -----------------------------
st.markdown(
    """
    <div class="main-title">Guest Posting Site Analyzer</div>
    <div class="sub-title">
        Domain list paste karo, DA/PA/Spam/Traffic fill karo, aur app Good / Average / Risky / Avoid decision dega.
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <div class="info-box">
        <b>Free MVP:</b> Website live check, HTTPS, WHOIS domain age, duplicate clean-up automatic hai.
        Ahrefs Traffic, DA, PA, Spam Score manually fill karne ke liye editable table diya gaya hai.
    </div>
    """,
    unsafe_allow_html=True
)


# -----------------------------
# Input
# -----------------------------
with st.sidebar:
    st.header("Input Sites")

    input_mode = st.radio(
        "Input type",
        ["Paste domain list", "Upload Excel/CSV"]
    )

    run_live = st.checkbox("Live/HTTPS check run karo", value=True)
    run_whois = st.checkbox("WHOIS domain age check run karo", value=True)

    st.caption("WHOIS check slow ho sakta hai. Pehle 20-50 domains se test karo.")


domains = []

if input_mode == "Paste domain list":
    raw_text = st.text_area(
        "Domain/URL list paste karo, one per line",
        height=220,
        placeholder="example.com\nhttps://www.sample.com/blog\nanother-site.in"
    )

    domains = [x.strip() for x in raw_text.splitlines() if x.strip()]

else:
    uploaded = st.file_uploader(
        "Upload Excel/CSV file",
        type=["xlsx", "xls", "csv"]
    )

    if uploaded is not None:
        try:
            if uploaded.name.lower().endswith(".csv"):
                upload_df = pd.read_csv(uploaded)
            else:
                upload_df = pd.read_excel(uploaded)

            st.write("Uploaded columns:", list(upload_df.columns))

            possible_cols = list(upload_df.columns)
            selected_col = st.selectbox(
                "Website/domain column select karo",
                possible_cols
            )

            domains = upload_df[selected_col].dropna().astype(str).tolist()

        except Exception as e:
            st.error(f"File read nahi ho payi: {e}")

if not domains:
    st.info("Pehle domain list paste karo ya Excel/CSV upload karo.")
    st.stop()


if "guest_df" not in st.session_state:
    st.session_state.guest_df = build_initial_df(domains)

if st.button("Prepare / Reset Domain Table"):
    st.session_state.guest_df = build_initial_df(domains)
    st.rerun()


df = st.session_state.guest_df.copy()


# -----------------------------
# KPI before analysis
# -----------------------------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Total Input Domains</div>
            <div class="kpi-value">{len(domains)}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with c2:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Unique Domains</div>
            <div class="kpi-value">{len(df)}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with c3:
    duplicate_count = max(len(domains) - len(df), 0)
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Duplicates Removed</div>
            <div class="kpi-value">{duplicate_count}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with c4:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Ready for Analysis</div>
            <div class="kpi-value">Yes</div>
        </div>
        """,
        unsafe_allow_html=True
    )


st.markdown("---")


# -----------------------------
# Manual metrics editor
# -----------------------------
st.subheader("1. Fill Manual Metrics")

st.caption(
    "Yahan DA, PA, Spam Score, Ahrefs Traffic, Indexed Pages, Price fill kar sakte ho. "
    "Baaki checks app automatically add karega."
)

edited_df = st.data_editor(
    df,
    use_container_width=True,
    num_rows="fixed",
    key="editor",
    column_config={
        "DA": st.column_config.NumberColumn("DA", min_value=0, max_value=100),
        "PA": st.column_config.NumberColumn("PA", min_value=0, max_value=100),
        "Spam Score": st.column_config.NumberColumn("Spam Score", min_value=0, max_value=100),
        "Ahrefs Traffic": st.column_config.NumberColumn("Ahrefs Traffic", min_value=0),
        "Indexed Pages": st.column_config.NumberColumn("Indexed Pages", min_value=0),
        "Price": st.column_config.NumberColumn("Price", min_value=0),
    }
)

st.session_state.guest_df = edited_df.copy()


# -----------------------------
# Links for manual checks
# -----------------------------
st.subheader("2. Quick Manual Check Links")

link_df = edited_df[["Domain"]].copy()
link_df["Ahrefs Traffic Checker"] = link_df["Domain"].apply(ahrefs_link)
link_df["Google Index Check"] = link_df["Domain"].apply(google_index_link)
link_df["Moz DA/PA Check"] = link_df["Domain"].apply(moz_link)

st.dataframe(
    link_df,
    use_container_width=True,
    column_config={
        "Ahrefs Traffic Checker": st.column_config.LinkColumn("Ahrefs Traffic Checker"),
        "Google Index Check": st.column_config.LinkColumn("Google Index Check"),
        "Moz DA/PA Check": st.column_config.LinkColumn("Moz DA/PA Check"),
    }
)


# -----------------------------
# Analysis
# -----------------------------
st.subheader("3. Run Analysis")

if st.button("Run Guest Posting Analysis", type="primary"):
    result_df = edited_df.copy()

    live_rows = []
    age_rows = []

    progress = st.progress(0)
    status = st.empty()

    total = len(result_df)

    for i, domain in enumerate(result_df["Domain"].tolist()):
        status.write(f"Checking {i + 1}/{total}: {domain}")

        if run_live:
            live_data = check_live_status(domain)
        else:
            live_data = {
                "Live Status": "Skipped",
                "HTTPS": "Skipped",
                "Final URL": "",
                "HTTP Code": "",
                "Title": "",
            }

        if run_whois:
            age_data = get_domain_age(domain)
            time.sleep(0.4)
        else:
            age_data = {
                "Creation Date": "",
                "Domain Age Years": "",
                "WHOIS Status": "Skipped"
            }

        live_rows.append(live_data)
        age_rows.append(age_data)

        progress.progress((i + 1) / total)

    live_df = pd.DataFrame(live_rows)
    age_df = pd.DataFrame(age_rows)

    result_df = pd.concat([result_df.reset_index(drop=True), live_df, age_df], axis=1)

    result_df["Traffic Bucket"] = result_df["Ahrefs Traffic"].apply(traffic_bucket)

    scores = result_df.apply(score_site, axis=1)
    result_df["Score"] = [x[0] for x in scores]
    result_df["Decision"] = [x[1] for x in scores]
    result_df["Reason"] = [x[2] for x in scores]

    result_df = result_df.sort_values(
        by=["Decision", "Score"],
        ascending=[True, False]
    ).reset_index(drop=True)

    st.session_state.result_df = result_df

    status.empty()
    progress.empty()
    st.success("Analysis complete!")


if "result_df" in st.session_state:
    result_df = st.session_state.result_df.copy()

    st.markdown("---")
    st.subheader("Final Result")

    r1, r2, r3, r4 = st.columns(4)

    with r1:
        st.metric("Good", int((result_df["Decision"] == "Good").sum()))

    with r2:
        st.metric("Average", int((result_df["Decision"] == "Average").sum()))

    with r3:
        st.metric("Risky", int((result_df["Decision"] == "Risky").sum()))

    with r4:
        st.metric("Avoid", int((result_df["Decision"] == "Avoid").sum()))

    decision_filter = st.multiselect(
        "Decision filter",
        ["Good", "Average", "Risky", "Avoid"],
        default=["Good", "Average", "Risky", "Avoid"]
    )

    filtered_df = result_df[result_df["Decision"].isin(decision_filter)].copy()

    st.dataframe(
        filtered_df,
        use_container_width=True,
        column_config={
            "Final URL": st.column_config.LinkColumn("Final URL"),
        }
    )

    st.download_button(
        "Download Analysis Excel",
        data=to_excel(result_df),
        file_name="guest_posting_site_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
