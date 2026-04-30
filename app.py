import imaplib
import smtplib
import email
import sqlite3
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parseaddr, formataddr, make_msgid
from datetime import date, datetime
from bs4 import BeautifulSoup

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Mail Follow-up Dashboard",
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

    .mail-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        padding: 14px 16px;
        margin-bottom: 10px;
    }

    .mail-subject {
        font-size: 18px;
        font-weight: 800;
        color: #0f172a;
    }

    .mail-meta {
        color: #64748b;
        font-size: 13px;
        margin-top: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# -----------------------------
# Secrets / Config
# -----------------------------
def get_mail_config():
    try:
        return {
            "email": st.secrets["mail"]["email"],
            "app_password": st.secrets["mail"]["app_password"],
            "imap_server": st.secrets["mail"].get("imap_server", "imap.gmail.com"),
            "smtp_server": st.secrets["mail"].get("smtp_server", "smtp.gmail.com"),
            "smtp_port": int(st.secrets["mail"].get("smtp_port", 587)),
        }
    except Exception:
        st.error(
            "Mail secrets set nahi hain. Streamlit Secrets me [mail] config add karo."
        )
        st.stop()


MAIL_CONFIG = get_mail_config()
DB_PATH = "mail_followups.db"


# -----------------------------
# Database
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mail_uid TEXT,
            from_email TEXT,
            subject TEXT,
            followup_date TEXT,
            note TEXT,
            priority TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def add_followup(mail_uid, from_email, subject, followup_date, note, priority):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO followups
        (mail_uid, from_email, subject, followup_date, note, priority, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(mail_uid),
            from_email,
            subject,
            str(followup_date),
            note,
            priority,
            "Pending",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )

    conn.commit()
    conn.close()


def get_followups(status_filter=None):
    conn = sqlite3.connect(DB_PATH)

    if status_filter:
        df = pd.read_sql_query(
            "SELECT * FROM followups WHERE status = ? ORDER BY followup_date ASC, id DESC",
            conn,
            params=(status_filter,),
        )
    else:
        df = pd.read_sql_query(
            "SELECT * FROM followups ORDER BY followup_date ASC, id DESC",
            conn,
        )

    conn.close()
    return df


def mark_followup_done(followup_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "UPDATE followups SET status = 'Done' WHERE id = ?",
        (int(followup_id),),
    )

    conn.commit()
    conn.close()


def delete_followup(followup_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM followups WHERE id = ?",
        (int(followup_id),),
    )

    conn.commit()
    conn.close()


init_db()


# -----------------------------
# Mail helpers
# -----------------------------
def decode_mime_words(value):
    if not value:
        return ""

    decoded_parts = decode_header(value)
    output = ""

    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            try:
                output += part.decode(encoding or "utf-8", errors="ignore")
            except Exception:
                output += part.decode("utf-8", errors="ignore")
        else:
            output += str(part)

    return output.strip()


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n").strip()


def get_body_from_message(msg):
    plain_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")

            if "attachment" in disposition.lower():
                continue

            try:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"

                if payload:
                    decoded = payload.decode(charset, errors="ignore")

                    if content_type == "text/plain" and not plain_body:
                        plain_body = decoded

                    elif content_type == "text/html" and not html_body:
                        html_body = decoded

            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"

            if payload:
                decoded = payload.decode(charset, errors="ignore")

                if msg.get_content_type() == "text/html":
                    html_body = decoded
                else:
                    plain_body = decoded

        except Exception:
            pass

    if plain_body:
        return plain_body.strip()

    if html_body:
        return html_to_text(html_body)

    return ""


def imap_connect():
    mail = imaplib.IMAP4_SSL(MAIL_CONFIG["imap_server"])
    mail.login(MAIL_CONFIG["email"], MAIL_CONFIG["app_password"])
    return mail


def fetch_inbox(limit=20, search_text=""):
    mail = imap_connect()
    mail.select("INBOX")

    if search_text.strip():
        search_query = f'(TEXT "{search_text.strip()}")'
        status, data = mail.search(None, search_query)
    else:
        status, data = mail.search(None, "ALL")

    if status != "OK":
        mail.logout()
        return []

    ids = data[0].split()
    ids = ids[-limit:]
    ids.reverse()

    mails = []

    for num in ids:
        status, msg_data = mail.fetch(num, "(RFC822)")

        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime_words(msg.get("Subject"))
        from_raw = decode_mime_words(msg.get("From"))
        from_name, from_email = parseaddr(from_raw)

        date_raw = msg.get("Date", "")
        body = get_body_from_message(msg)

        mails.append(
            {
                "uid": num.decode(),
                "from_name": from_name,
                "from_email": from_email,
                "from_raw": from_raw,
                "subject": subject,
                "date": date_raw,
                "body": body,
                "message_id": msg.get("Message-ID", ""),
                "in_reply_to": msg.get("In-Reply-To", ""),
                "references": msg.get("References", ""),
            }
        )

    mail.logout()
    return mails


def send_new_mail(to_email, subject, body, cc_email=""):
    msg = EmailMessage()
    msg["From"] = MAIL_CONFIG["email"]
    msg["To"] = to_email

    if cc_email.strip():
        msg["Cc"] = cc_email.strip()

    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)

    recipients = [x.strip() for x in to_email.split(",") if x.strip()]

    if cc_email.strip():
        recipients += [x.strip() for x in cc_email.split(",") if x.strip()]

    with smtplib.SMTP(MAIL_CONFIG["smtp_server"], MAIL_CONFIG["smtp_port"]) as server:
        server.starttls()
        server.login(MAIL_CONFIG["email"], MAIL_CONFIG["app_password"])
        server.send_message(msg, to_addrs=recipients)


def send_reply(original_mail, reply_body):
    to_email = original_mail["from_email"]
    subject = original_mail["subject"]

    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    msg = EmailMessage()
    msg["From"] = MAIL_CONFIG["email"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()

    if original_mail.get("message_id"):
        msg["In-Reply-To"] = original_mail["message_id"]

    references = original_mail.get("references") or ""

    if original_mail.get("message_id"):
        references = (references + " " + original_mail["message_id"]).strip()

    if references:
        msg["References"] = references

    final_body = reply_body.strip()

    msg.set_content(final_body)

    with smtplib.SMTP(MAIL_CONFIG["smtp_server"], MAIL_CONFIG["smtp_port"]) as server:
        server.starttls()
        server.login(MAIL_CONFIG["email"], MAIL_CONFIG["app_password"])
        server.send_message(msg)


# -----------------------------
# Header
# -----------------------------
st.markdown(
    """
    <div class="main-title">Mail Follow-up Dashboard</div>
    <div class="sub-title">
        Inbox read karo, new mail bhejo, reply karo, aur important emails ke follow-ups track karo.
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="info-box">
        Connected mailbox: <b>{MAIL_CONFIG["email"]}</b><br>
        Basic MVP: read inbox, send mail, reply mail, follow-up add/list/done.
    </div>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("Navigation")

    page = st.radio(
        "Go to",
        ["Inbox", "Compose", "Follow-ups"],
    )

    st.markdown("---")

    inbox_limit = st.number_input(
        "Inbox mail limit",
        min_value=5,
        max_value=100,
        value=20,
        step=5,
    )


# -----------------------------
# Follow-up KPIs
# -----------------------------
follow_df_all = get_followups()

today_str = date.today().strftime("%Y-%m-%d")

if not follow_df_all.empty:
    pending_df = follow_df_all[follow_df_all["status"] == "Pending"].copy()
    today_count = int((pending_df["followup_date"] == today_str).sum())
    overdue_count = int((pending_df["followup_date"] < today_str).sum())
    upcoming_count = int((pending_df["followup_date"] > today_str).sum())
else:
    today_count = 0
    overdue_count = 0
    upcoming_count = 0

k1, k2, k3, k4 = st.columns(4)

with k1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Today Follow-ups</div>
            <div class="kpi-value">{today_count}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with k2:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Overdue</div>
            <div class="kpi-value">{overdue_count}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with k3:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Upcoming</div>
            <div class="kpi-value">{upcoming_count}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with k4:
    total_pending = today_count + overdue_count + upcoming_count
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Total Pending</div>
            <div class="kpi-value">{total_pending}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")


# -----------------------------
# Inbox page
# -----------------------------
if page == "Inbox":
    st.subheader("Inbox")

    search_text = st.text_input(
        "Search inbox",
        placeholder="sender, subject, keyword..."
    )

    refresh = st.button("Refresh Inbox", type="primary")

    if "inbox_mails" not in st.session_state or refresh:
        with st.spinner("Inbox loading..."):
            try:
                st.session_state.inbox_mails = fetch_inbox(
                    limit=int(inbox_limit),
                    search_text=search_text,
                )
            except Exception as e:
                st.error(f"Inbox fetch nahi ho paya: {e}")
                st.stop()

    mails = st.session_state.inbox_mails

    if not mails:
        st.info("No mails found.")
        st.stop()

    mail_options = []

    for idx, m in enumerate(mails):
        label = f"{idx + 1}. {m['subject'][:70]} | {m['from_email']} | {m['date'][:25]}"
        mail_options.append(label)

    selected_label = st.selectbox(
        "Mail select karo",
        mail_options,
    )

    selected_index = mail_options.index(selected_label)
    selected_mail = mails[selected_index]

    st.markdown(
        f"""
        <div class="mail-card">
            <div class="mail-subject">{selected_mail["subject"]}</div>
            <div class="mail-meta">
                From: {selected_mail["from_raw"]}<br>
                Date: {selected_mail["date"]}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["Mail Body", "Reply", "Add Follow-up"])

    with tab1:
        st.text_area(
            "Message",
            selected_mail["body"],
            height=430,
        )

    with tab2:
        reply_body = st.text_area(
            "Reply message",
            height=220,
            placeholder="Reply type karo..."
        )

        if st.button("Send Reply"):
            if not reply_body.strip():
                st.warning("Reply message blank hai.")
            else:
                try:
                    send_reply(selected_mail, reply_body)
                    st.success("Reply sent successfully.")
                except Exception as e:
                    st.error(f"Reply send nahi ho paya: {e}")

    with tab3:
        with st.form("followup_form"):
            followup_date = st.date_input(
                "Follow-up date",
                value=date.today(),
            )

            priority = st.selectbox(
                "Priority",
                ["Medium", "High", "Low"],
            )

            note = st.text_area(
                "Follow-up note",
                placeholder="Is mail ka follow-up kis baat ke liye lena hai?"
            )

            submit_followup = st.form_submit_button("Add Follow-up")

        if submit_followup:
            add_followup(
                mail_uid=selected_mail["uid"],
                from_email=selected_mail["from_email"],
                subject=selected_mail["subject"],
                followup_date=followup_date,
                note=note,
                priority=priority,
            )

            st.success("Follow-up added.")


# -----------------------------
# Compose page
# -----------------------------
elif page == "Compose":
    st.subheader("Compose New Mail")

    with st.form("compose_form"):
        to_email = st.text_input("To", placeholder="customer@example.com")
        cc_email = st.text_input("CC", placeholder="optional")
        subject = st.text_input("Subject")
        body = st.text_area("Message", height=320)

        send_btn = st.form_submit_button("Send Mail")

    if send_btn:
        if not to_email.strip() or not subject.strip() or not body.strip():
            st.warning("To, Subject aur Message required hain.")
        else:
            try:
                send_new_mail(
                    to_email=to_email,
                    cc_email=cc_email,
                    subject=subject,
                    body=body,
                )
                st.success("Mail sent successfully.")
            except Exception as e:
                st.error(f"Mail send nahi ho paya: {e}")


# -----------------------------
# Follow-ups page
# -----------------------------
elif page == "Follow-ups":
    st.subheader("Follow-ups")

    follow_df = get_followups()

    if follow_df.empty:
        st.info("Abhi koi follow-up add nahi hai.")
        st.stop()

    status_filter = st.selectbox(
        "Status filter",
        ["Pending", "Done", "All"],
    )

    filtered = follow_df.copy()

    if status_filter != "All":
        filtered = filtered[filtered["status"] == status_filter].copy()

    date_filter = st.selectbox(
        "Date filter",
        ["All", "Overdue", "Today", "Upcoming"],
    )

    if date_filter == "Overdue":
        filtered = filtered[
            (filtered["status"] == "Pending")
            & (filtered["followup_date"] < today_str)
        ].copy()
    elif date_filter == "Today":
        filtered = filtered[
            (filtered["status"] == "Pending")
            & (filtered["followup_date"] == today_str)
        ].copy()
    elif date_filter == "Upcoming":
        filtered = filtered[
            (filtered["status"] == "Pending")
            & (filtered["followup_date"] > today_str)
        ].copy()

    st.dataframe(
        filtered,
        use_container_width=True,
    )

    st.markdown("---")

    st.subheader("Update Follow-up")

    pending_or_all = filtered.copy()

    if pending_or_all.empty:
        st.info("Selected filter me koi follow-up nahi hai.")
    else:
        options = []

        for _, row in pending_or_all.iterrows():
            label = (
                f"#{row['id']} | {row['followup_date']} | "
                f"{row['priority']} | {row['from_email']} | {row['subject'][:60]}"
            )
            options.append(label)

        selected = st.selectbox("Follow-up select karo", options)

        selected_id = int(selected.split("|")[0].replace("#", "").strip())

        c_done, c_delete = st.columns(2)

        with c_done:
            if st.button("Mark as Done"):
                mark_followup_done(selected_id)
                st.success("Follow-up marked as done.")
                st.rerun()

        with c_delete:
            if st.button("Delete Follow-up"):
                delete_followup(selected_id)
                st.success("Follow-up deleted.")
                st.rerun()
