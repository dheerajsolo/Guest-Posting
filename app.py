import imaplib
import smtplib
import email
import sqlite3
import re
from io import BytesIO
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parseaddr, make_msgid
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup

import pandas as pd
import streamlit as st


# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="Advanced Mail Follow-up CRM",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = "mail_crm_dashboard.db"


# =========================================================
# STYLE
# =========================================================

st.markdown(
    """
    <style>
    .stApp {
        background: #f6f8fb;
    }

    .block-container {
        padding-top: 1.2rem;
        max-width: 1500px;
    }

    .main-title {
        font-size: 38px;
        font-weight: 900;
        color: #0f172a;
        margin-bottom: 2px;
        letter-spacing: -0.8px;
    }

    .sub-title {
        color: #64748b;
        font-size: 15px;
        margin-bottom: 18px;
    }

    .card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045);
    }

    .kpi-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 16px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
        min-height: 108px;
    }

    .kpi-label {
        color: #64748b;
        font-size: 13px;
        font-weight: 700;
    }

    .kpi-value {
        color: #0f172a;
        font-size: 30px;
        font-weight: 900;
        margin-top: 6px;
    }

    .mail-subject {
        font-size: 20px;
        font-weight: 850;
        color: #0f172a;
        margin-bottom: 6px;
    }

    .mail-meta {
        color: #64748b;
        font-size: 13px;
        line-height: 1.5;
    }

    .pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 800;
        margin-right: 6px;
        border: 1px solid #e5e7eb;
        background: #f8fafc;
        color: #334155;
    }

    .pill-red {
        background: #fef2f2;
        color: #991b1b;
        border-color: #fecaca;
    }

    .pill-green {
        background: #f0fdf4;
        color: #166534;
        border-color: #bbf7d0;
    }

    .pill-orange {
        background: #fff7ed;
        color: #9a3412;
        border-color: #fed7aa;
    }

    .pill-blue {
        background: #eff6ff;
        color: #1d4ed8;
        border-color: #bfdbfe;
    }

    div[data-testid="stDataFrame"] {
        border-radius: 14px;
        overflow: hidden;
        border: 1px solid #e5e7eb;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# SECRETS
# =========================================================

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
        st.error("Mail secrets missing hain. Streamlit Settings → Secrets me [mail] config add karo.")
        st.stop()


def app_auth_enabled():
    try:
        return bool(st.secrets["app_auth"].get("enabled", False))
    except Exception:
        return False


def check_app_login():
    if not app_auth_enabled():
        return True

    if "app_logged_in" not in st.session_state:
        st.session_state.app_logged_in = False

    if st.session_state.app_logged_in:
        return True

    st.markdown('<div class="main-title">Login Required</div>', unsafe_allow_html=True)
    st.caption("Mail dashboard access ke liye login karo.")

    with st.form("app_login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

    if submit:
        correct_username = st.secrets["app_auth"]["username"]
        correct_password = st.secrets["app_auth"]["password"]

        if username == correct_username and password == correct_password:
            st.session_state.app_logged_in = True
            st.rerun()
        else:
            st.error("Wrong username/password.")

    return False


MAIL_CONFIG = get_mail_config()

if not check_app_login():
    st.stop()


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mail_uid TEXT,
            message_id TEXT,
            thread_ref TEXT,
            from_name TEXT,
            from_email TEXT,
            subject TEXT,
            followup_date TEXT,
            note TEXT,
            next_action TEXT,
            priority TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'Pending',
            tags TEXT,
            source TEXT DEFAULT 'Inbox',
            created_at TEXT,
            updated_at TEXT,
            done_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            phone TEXT,
            company TEXT,
            category TEXT,
            notes TEXT,
            tags TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            subject TEXT,
            body TEXT,
            category TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            to_email TEXT,
            cc_email TEXT,
            subject TEXT,
            body TEXT,
            sent_type TEXT,
            related_followup_id INTEGER,
            sent_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def seed_templates():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM templates")
    count = cur.fetchone()[0]

    if count == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        default_templates = [
            (
                "Guest Post Follow-up",
                "Follow-up regarding guest post placement",
                "Hi,\n\nJust following up on my previous email regarding the guest post placement.\n\nPlease share the updated details, pricing, and publishing timeline.\n\nRegards,\n",
                "Guest Posting",
            ),
            (
                "Payment Reminder",
                "Payment confirmation reminder",
                "Hi,\n\nThis is a quick reminder regarding the pending payment confirmation.\n\nPlease confirm once done.\n\nRegards,\n",
                "Payment",
            ),
            (
                "Order/Customer Support Reply",
                "Re: Your query",
                "Hi,\n\nThanks for reaching out.\n\nWe are checking this and will update you shortly.\n\nRegards,\n",
                "Support",
            ),
        ]

        for name, subject, body, category in default_templates:
            cur.execute(
                """
                INSERT INTO templates (name, subject, body, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, subject, body, category, now, now),
            )

    conn.commit()
    conn.close()


init_db()
seed_templates()


# =========================================================
# DATABASE HELPERS
# =========================================================

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def upsert_contact(name, email_addr, phone="", company="", category="", notes="", tags=""):
    if not email_addr:
        return

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT id FROM contacts WHERE email = ?", (email_addr,))
    existing = cur.fetchone()

    if existing:
        cur.execute(
            """
            UPDATE contacts
            SET name = COALESCE(NULLIF(?, ''), name),
                phone = COALESCE(NULLIF(?, ''), phone),
                company = COALESCE(NULLIF(?, ''), company),
                category = COALESCE(NULLIF(?, ''), category),
                notes = COALESCE(NULLIF(?, ''), notes),
                tags = COALESCE(NULLIF(?, ''), tags),
                updated_at = ?
            WHERE email = ?
            """,
            (name, phone, company, category, notes, tags, now_str(), email_addr),
        )
    else:
        cur.execute(
            """
            INSERT INTO contacts
            (name, email, phone, company, category, notes, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email_addr, phone, company, category, notes, tags, now_str(), now_str()),
        )

    conn.commit()
    conn.close()


def add_followup(data):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO followups
        (
            mail_uid, message_id, thread_ref, from_name, from_email, subject,
            followup_date, note, next_action, priority, status, tags, source,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(data.get("mail_uid", "")),
            data.get("message_id", ""),
            data.get("thread_ref", ""),
            data.get("from_name", ""),
            data.get("from_email", ""),
            data.get("subject", ""),
            str(data.get("followup_date", date.today())),
            data.get("note", ""),
            data.get("next_action", ""),
            data.get("priority", "Medium"),
            data.get("status", "Pending"),
            data.get("tags", ""),
            data.get("source", "Inbox"),
            now_str(),
            now_str(),
        ),
    )

    conn.commit()
    conn.close()

    upsert_contact(
        name=data.get("from_name", ""),
        email_addr=data.get("from_email", ""),
        notes=data.get("note", ""),
        tags=data.get("tags", ""),
    )


def get_table(table_name):
    conn = db_connect()
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    conn.close()
    return df


def get_followups():
    conn = db_connect()
    df = pd.read_sql_query("SELECT * FROM followups ORDER BY followup_date ASC, id DESC", conn)
    conn.close()
    return df


def update_followup_status(followup_id, status):
    conn = db_connect()
    cur = conn.cursor()

    done_at = now_str() if status == "Done" else None

    cur.execute(
        """
        UPDATE followups
        SET status = ?, updated_at = ?, done_at = ?
        WHERE id = ?
        """,
        (status, now_str(), done_at, int(followup_id)),
    )

    conn.commit()
    conn.close()


def snooze_followup(followup_id, days):
    conn = db_connect()
    cur = conn.cursor()

    new_date = (date.today() + timedelta(days=int(days))).strftime("%Y-%m-%d")

    cur.execute(
        """
        UPDATE followups
        SET followup_date = ?, status = 'Snoozed', updated_at = ?
        WHERE id = ?
        """,
        (new_date, now_str(), int(followup_id)),
    )

    conn.commit()
    conn.close()


def delete_followup(followup_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM followups WHERE id = ?", (int(followup_id),))
    conn.commit()
    conn.close()


def update_followup_fields(followup_id, followup_date, priority, status, note, next_action, tags):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE followups
        SET followup_date = ?, priority = ?, status = ?, note = ?, next_action = ?, tags = ?, updated_at = ?
        WHERE id = ?
        """,
        (str(followup_date), priority, status, note, next_action, tags, now_str(), int(followup_id)),
    )

    conn.commit()
    conn.close()


def add_template(name, subject, body, category):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO templates (name, subject, body, category, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name, subject, body, category, now_str(), now_str()),
    )

    conn.commit()
    conn.close()


def delete_template(template_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM templates WHERE id = ?", (int(template_id),))
    conn.commit()
    conn.close()


def log_sent_mail(to_email, cc_email, subject, body, sent_type, related_followup_id=None):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sent_log
        (to_email, cc_email, subject, body, sent_type, related_followup_id, sent_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (to_email, cc_email, subject, body, sent_type, related_followup_id, now_str()),
    )

    conn.commit()
    conn.close()


# =========================================================
# MAIL HELPERS
# =========================================================

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
    for tag in soup(["script", "style"]):
        tag.extract()
    return soup.get_text(separator="\n").strip()


def clean_body_text(text):
    if not text:
        return ""

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text


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
        return clean_body_text(plain_body)

    if html_body:
        return clean_body_text(html_to_text(html_body))

    return ""


def get_attachments_info(msg):
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition") or "")
            filename = part.get_filename()

            if "attachment" in disposition.lower() or filename:
                filename = decode_mime_words(filename or "attachment")
                content_type = part.get_content_type()
                size = 0

                try:
                    payload = part.get_payload(decode=True)
                    size = len(payload) if payload else 0
                except Exception:
                    size = 0

                attachments.append(
                    {
                        "filename": filename,
                        "content_type": content_type,
                        "size_kb": round(size / 1024, 2),
                    }
                )

    return attachments


def imap_connect():
    mail = imaplib.IMAP4_SSL(MAIL_CONFIG["imap_server"])
    mail.login(MAIL_CONFIG["email"], MAIL_CONFIG["app_password"])
    return mail


def build_imap_search_query(search_text="", unread_only=False, from_filter=""):
    parts = []

    if unread_only:
        parts.append("UNSEEN")

    if from_filter.strip():
        parts.append(f'FROM "{from_filter.strip()}"')

    if search_text.strip():
        parts.append(f'TEXT "{search_text.strip()}"')

    if not parts:
        return "ALL"

    return "(" + " ".join(parts) + ")"


def fetch_inbox(limit=20, search_text="", unread_only=False, from_filter=""):
    mail = imap_connect()
    mail.select("INBOX")

    search_query = build_imap_search_query(search_text, unread_only, from_filter)
    status, data = mail.search(None, search_query)

    if status != "OK":
        mail.logout()
        return []

    ids = data[0].split()
    ids = ids[-int(limit):]
    ids.reverse()

    mails = []

    for num in ids:
        status, msg_data = mail.fetch(num, "(RFC822 FLAGS)")

        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime_words(msg.get("Subject"))
        from_raw = decode_mime_words(msg.get("From"))
        from_name, from_email = parseaddr(from_raw)

        to_raw = decode_mime_words(msg.get("To"))
        date_raw = msg.get("Date", "")
        body = get_body_from_message(msg)
        attachments = get_attachments_info(msg)

        flags_text = ""
        try:
            flags_text = str(msg_data[1])
        except Exception:
            flags_text = ""

        unread = "\\Seen" not in flags_text

        mails.append(
            {
                "uid": num.decode(),
                "from_name": from_name,
                "from_email": from_email,
                "from_raw": from_raw,
                "to_raw": to_raw,
                "subject": subject,
                "date": date_raw,
                "body": body,
                "message_id": msg.get("Message-ID", ""),
                "in_reply_to": msg.get("In-Reply-To", ""),
                "references": msg.get("References", ""),
                "attachments": attachments,
                "unread": unread,
            }
        )

    mail.logout()
    return mails


def send_mail(to_email, subject, body, cc_email="", bcc_email="", sent_type="New", related_followup_id=None):
    msg = EmailMessage()
    msg["From"] = MAIL_CONFIG["email"]
    msg["To"] = to_email

    if cc_email.strip():
        msg["Cc"] = cc_email.strip()

    if bcc_email.strip():
        msg["Bcc"] = bcc_email.strip()

    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)

    recipients = [x.strip() for x in to_email.split(",") if x.strip()]

    if cc_email.strip():
        recipients += [x.strip() for x in cc_email.split(",") if x.strip()]

    if bcc_email.strip():
        recipients += [x.strip() for x in bcc_email.split(",") if x.strip()]

    with smtplib.SMTP(MAIL_CONFIG["smtp_server"], MAIL_CONFIG["smtp_port"]) as server:
        server.starttls()
        server.login(MAIL_CONFIG["email"], MAIL_CONFIG["app_password"])
        server.send_message(msg, to_addrs=recipients)

    log_sent_mail(to_email, cc_email, subject, body, sent_type, related_followup_id)


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

    quoted = "\n\n--- Original Message ---\n"
    quoted += f"From: {original_mail.get('from_raw', '')}\n"
    quoted += f"Date: {original_mail.get('date', '')}\n"
    quoted += f"Subject: {original_mail.get('subject', '')}\n\n"
    quoted += original_mail.get("body", "")[:2000]

    msg.set_content(reply_body.strip() + quoted)

    with smtplib.SMTP(MAIL_CONFIG["smtp_server"], MAIL_CONFIG["smtp_port"]) as server:
        server.starttls()
        server.login(MAIL_CONFIG["email"], MAIL_CONFIG["app_password"])
        server.send_message(msg)

    log_sent_mail(to_email, "", subject, reply_body, "Reply", None)


# =========================================================
# EXPORT HELPERS
# =========================================================

def df_to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")


def all_db_to_excel():
    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for table in ["followups", "contacts", "templates", "sent_log"]:
            df = get_table(table)
            df.to_excel(writer, sheet_name=table[:31], index=False)

    return buffer.getvalue()


# =========================================================
# HEADER
# =========================================================

st.markdown(
    """
    <div class="main-title">Advanced Mail Follow-up CRM</div>
    <div class="sub-title">
        Inbox, replies, new mails, follow-ups, contact CRM, templates aur analytics — ek dashboard me.
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="card">
        Connected mailbox: <b>{MAIL_CONFIG["email"]}</b><br>
        Use case: customer support, supplier follow-up, guest post follow-up, payment reminder, outreach tracking.
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.header("Navigation")

    page = st.radio(
        "Go to",
        [
            "Dashboard",
            "Inbox",
            "Compose",
            "Follow-ups",
            "Contacts",
            "Templates",
            "Sent Log",
            "Backup",
        ],
    )

    st.markdown("---")

    inbox_limit = st.number_input(
        "Inbox mail limit",
        min_value=5,
        max_value=200,
        value=30,
        step=5,
    )

    if app_auth_enabled():
        st.markdown("---")
        if st.button("Logout dashboard"):
            st.session_state.app_logged_in = False
            st.rerun()


# =========================================================
# GLOBAL KPIS
# =========================================================

follow_df_all = get_followups()
today_str = date.today().strftime("%Y-%m-%d")

if not follow_df_all.empty:
    pending_df = follow_df_all[follow_df_all["status"].isin(["Pending", "Snoozed", "Waiting"])].copy()
    today_count = int((pending_df["followup_date"] == today_str).sum())
    overdue_count = int((pending_df["followup_date"] < today_str).sum())
    upcoming_count = int((pending_df["followup_date"] > today_str).sum())
    done_count = int((follow_df_all["status"] == "Done").sum())
else:
    pending_df = pd.DataFrame()
    today_count = 0
    overdue_count = 0
    upcoming_count = 0
    done_count = 0

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


# =========================================================
# PAGE: DASHBOARD
# =========================================================

if page == "Dashboard":
    st.subheader("Command Dashboard")

    c1, c2 = st.columns([1.2, 1])

    with c1:
        st.markdown("### Urgent Follow-ups")

        if follow_df_all.empty:
            st.info("Abhi koi follow-up nahi hai.")
        else:
            urgent = follow_df_all[
                (follow_df_all["status"].isin(["Pending", "Snoozed", "Waiting"]))
                & (follow_df_all["followup_date"] <= today_str)
            ].copy()

            if urgent.empty:
                st.success("Aaj/overdue follow-up clear hai.")
            else:
                urgent = urgent.sort_values(["followup_date", "priority"], ascending=[True, True])
                st.dataframe(
                    urgent[
                        [
                            "id",
                            "followup_date",
                            "priority",
                            "status",
                            "from_email",
                            "subject",
                            "next_action",
                            "tags",
                        ]
                    ],
                    use_container_width=True,
                )

    with c2:
        st.markdown("### Status Split")

        if follow_df_all.empty:
            st.info("No data.")
        else:
            status_counts = follow_df_all["status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            st.dataframe(status_counts, use_container_width=True)

            priority_counts = follow_df_all["priority"].value_counts().reset_index()
            priority_counts.columns = ["Priority", "Count"]

            st.markdown("### Priority Split")
            st.dataframe(priority_counts, use_container_width=True)

    st.markdown("---")

    st.markdown("### Quick Actions")

    qa1, qa2, qa3 = st.columns(3)

    with qa1:
        if st.button("Open Inbox"):
            st.session_state["_nav_target"] = "Inbox"
            st.info("Sidebar se Inbox open karo.")

    with qa2:
        if st.button("Open Follow-ups"):
            st.session_state["_nav_target"] = "Follow-ups"
            st.info("Sidebar se Follow-ups open karo.")

    with qa3:
        if st.button("Download Full Backup"):
            st.download_button(
                "Download Excel Backup",
                data=all_db_to_excel(),
                file_name="mail_crm_backup.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# =========================================================
# PAGE: INBOX
# =========================================================

elif page == "Inbox":
    st.subheader("Inbox")

    f1, f2, f3, f4 = st.columns([1.2, 1, 0.7, 0.7])

    with f1:
        search_text = st.text_input("Search inbox", placeholder="keyword, subject, message...")

    with f2:
        from_filter = st.text_input("From filter", placeholder="sender@email.com")

    with f3:
        unread_only = st.checkbox("Unread only", value=False)

    with f4:
        refresh = st.button("Refresh Inbox", type="primary")

    if "inbox_mails" not in st.session_state or refresh:
        with st.spinner("Inbox loading..."):
            try:
                st.session_state.inbox_mails = fetch_inbox(
                    limit=int(inbox_limit),
                    search_text=search_text,
                    unread_only=unread_only,
                    from_filter=from_filter,
                )
            except Exception as e:
                st.error(f"Inbox fetch nahi ho paya: {e}")
                st.stop()

    mails = st.session_state.inbox_mails

    if not mails:
        st.info("No mails found.")
        st.stop()

    mail_rows = []
    for idx, m in enumerate(mails):
        mail_rows.append(
            {
                "Index": idx,
                "Unread": "Yes" if m.get("unread", False) else "No",
                "From": m["from_email"],
                "Subject": m["subject"],
                "Date": m["date"][:30],
                "Attachments": len(m["attachments"]),
            }
        )

    mail_df = pd.DataFrame(mail_rows)

    st.dataframe(mail_df.drop(columns=["Index"]), use_container_width=True)

    options = []
    for idx, m in enumerate(mails):
        unread_label = "UNREAD" if m.get("unread", False) else "READ"
        label = f"{idx + 1}. [{unread_label}] {m['subject'][:80]} | {m['from_email']} | {m['date'][:25]}"
        options.append(label)

    selected_label = st.selectbox("Mail select karo", options)
    selected_index = options.index(selected_label)
    selected_mail = mails[selected_index]

    st.markdown(
        f"""
        <div class="card">
            <div class="mail-subject">{selected_mail["subject"]}</div>
            <div class="mail-meta">
                From: {selected_mail["from_raw"]}<br>
                To: {selected_mail["to_raw"]}<br>
                Date: {selected_mail["date"]}<br>
                Attachments: {len(selected_mail["attachments"])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["Mail Body", "Reply", "Add Follow-up", "Contact", "Attachments"])

    with tabs[0]:
        st.text_area("Message", selected_mail["body"], height=480)

    with tabs[1]:
        template_df = get_table("templates")

        template_choice = "Blank"
        template_body = ""

        if not template_df.empty:
            template_names = ["Blank"] + template_df["name"].tolist()
            template_choice = st.selectbox("Use template", template_names, key="reply_template")

            if template_choice != "Blank":
                row = template_df[template_df["name"] == template_choice].iloc[0]
                template_body = row["body"]

        reply_body = st.text_area(
            "Reply message",
            value=template_body,
            height=260,
            placeholder="Reply type karo..."
        )

        if st.button("Send Reply", type="primary"):
            if not reply_body.strip():
                st.warning("Reply message blank hai.")
            else:
                try:
                    send_reply(selected_mail, reply_body)
                    st.success("Reply sent successfully.")
                except Exception as e:
                    st.error(f"Reply send nahi ho paya: {e}")

    with tabs[2]:
        with st.form("followup_form"):
            followup_date = st.date_input("Follow-up date", value=date.today())
            priority = st.selectbox("Priority", ["High", "Medium", "Low"], index=1)
            status = st.selectbox("Status", ["Pending", "Waiting", "Snoozed"], index=0)
            tags = st.text_input("Tags", placeholder="guest-post, payment, supplier")
            next_action = st.text_input("Next action", placeholder="Call, reply, payment confirm, price ask...")
            note = st.text_area("Follow-up note", placeholder="Is mail ka follow-up kis baat ke liye lena hai?")

            submit_followup = st.form_submit_button("Add Follow-up")

        if submit_followup:
            add_followup(
                {
                    "mail_uid": selected_mail["uid"],
                    "message_id": selected_mail["message_id"],
                    "thread_ref": selected_mail["references"],
                    "from_name": selected_mail["from_name"],
                    "from_email": selected_mail["from_email"],
                    "subject": selected_mail["subject"],
                    "followup_date": followup_date,
                    "note": note,
                    "next_action": next_action,
                    "priority": priority,
                    "status": status,
                    "tags": tags,
                    "source": "Inbox",
                }
            )
            st.success("Follow-up added.")

    with tabs[3]:
        st.markdown("### Save / Update Contact")

        with st.form("contact_form"):
            name = st.text_input("Name", value=selected_mail["from_name"])
            email_addr = st.text_input("Email", value=selected_mail["from_email"])
            phone = st.text_input("Phone")
            company = st.text_input("Company")
            category = st.selectbox("Category", ["Customer", "Supplier", "Guest Post", "Agency", "Other"])
            tags = st.text_input("Tags", placeholder="vip, guest-post, urgent")
            notes = st.text_area("Notes")

            save_contact = st.form_submit_button("Save Contact")

        if save_contact:
            upsert_contact(name, email_addr, phone, company, category, notes, tags)
            st.success("Contact saved/updated.")

    with tabs[4]:
        if not selected_mail["attachments"]:
            st.info("No attachments detected.")
        else:
            st.dataframe(pd.DataFrame(selected_mail["attachments"]), use_container_width=True)


# =========================================================
# PAGE: COMPOSE
# =========================================================

elif page == "Compose":
    st.subheader("Compose New Mail")

    template_df = get_table("templates")

    selected_template = "Blank"
    default_subject = ""
    default_body = ""

    if not template_df.empty:
        template_names = ["Blank"] + template_df["name"].tolist()
        selected_template = st.selectbox("Template", template_names)

        if selected_template != "Blank":
            row = template_df[template_df["name"] == selected_template].iloc[0]
            default_subject = row["subject"]
            default_body = row["body"]

    with st.form("compose_form"):
        to_email = st.text_input("To", placeholder="customer@example.com")
        cc_email = st.text_input("CC", placeholder="optional")
        bcc_email = st.text_input("BCC", placeholder="optional")
        subject = st.text_input("Subject", value=default_subject)
        body = st.text_area("Message", value=default_body, height=340)

        send_btn = st.form_submit_button("Send Mail")

    if send_btn:
        if not to_email.strip() or not subject.strip() or not body.strip():
            st.warning("To, Subject aur Message required hain.")
        else:
            try:
                send_mail(
                    to_email=to_email,
                    cc_email=cc_email,
                    bcc_email=bcc_email,
                    subject=subject,
                    body=body,
                    sent_type="New",
                )
                st.success("Mail sent successfully.")
            except Exception as e:
                st.error(f"Mail send nahi ho paya: {e}")


# =========================================================
# PAGE: FOLLOW-UPS
# =========================================================

elif page == "Follow-ups":
    st.subheader("Follow-ups")

    follow_df = get_followups()

    if follow_df.empty:
        st.info("Abhi koi follow-up add nahi hai.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        status_filter = st.multiselect(
            "Status",
            ["Pending", "Waiting", "Snoozed", "Done"],
            default=["Pending", "Waiting", "Snoozed"],
        )

    with c2:
        priority_filter = st.multiselect(
            "Priority",
            ["High", "Medium", "Low"],
            default=["High", "Medium", "Low"],
        )

    with c3:
        date_filter = st.selectbox("Date", ["All", "Overdue", "Today", "Upcoming"])

    with c4:
        keyword = st.text_input("Search", placeholder="email, subject, tag...")

    filtered = follow_df.copy()

    filtered = filtered[filtered["status"].isin(status_filter)]
    filtered = filtered[filtered["priority"].isin(priority_filter)]

    if date_filter == "Overdue":
        filtered = filtered[filtered["followup_date"] < today_str]
    elif date_filter == "Today":
        filtered = filtered[filtered["followup_date"] == today_str]
    elif date_filter == "Upcoming":
        filtered = filtered[filtered["followup_date"] > today_str]

    if keyword.strip():
        k = keyword.lower()
        filtered = filtered[
            filtered.apply(
                lambda r: k in " ".join([str(x).lower() for x in r.values]),
                axis=1
            )
        ]

    st.dataframe(
        filtered[
            [
                "id",
                "followup_date",
                "priority",
                "status",
                "from_email",
                "subject",
                "next_action",
                "note",
                "tags",
                "created_at",
            ]
        ],
        use_container_width=True,
    )

    st.markdown("---")
    st.subheader("Manage Selected Follow-up")

    if filtered.empty:
        st.info("Selected filter me koi follow-up nahi hai.")
    else:
        options = []
        for _, row in filtered.iterrows():
            label = f"#{row['id']} | {row['followup_date']} | {row['priority']} | {row['from_email']} | {row['subject'][:70]}"
            options.append(label)

        selected = st.selectbox("Follow-up select karo", options)
        selected_id = int(selected.split("|")[0].replace("#", "").strip())

        row = follow_df[follow_df["id"] == selected_id].iloc[0]

        tab_edit, tab_action, tab_send = st.tabs(["Edit", "Quick Actions", "Send Mail"])

        with tab_edit:
            with st.form("edit_followup_form"):
                new_date = st.date_input("Follow-up date", value=datetime.strptime(row["followup_date"], "%Y-%m-%d").date())
                new_priority = st.selectbox("Priority", ["High", "Medium", "Low"], index=["High", "Medium", "Low"].index(row["priority"]))
                new_status = st.selectbox("Status", ["Pending", "Waiting", "Snoozed", "Done"], index=["Pending", "Waiting", "Snoozed", "Done"].index(row["status"]))
                new_next_action = st.text_input("Next action", value=row["next_action"] or "")
                new_tags = st.text_input("Tags", value=row["tags"] or "")
                new_note = st.text_area("Note", value=row["note"] or "", height=180)

                save_edit = st.form_submit_button("Save Changes")

            if save_edit:
                update_followup_fields(selected_id, new_date, new_priority, new_status, new_note, new_next_action, new_tags)
                st.success("Follow-up updated.")
                st.rerun()

        with tab_action:
            a1, a2, a3, a4, a5 = st.columns(5)

            with a1:
                if st.button("Mark Done"):
                    update_followup_status(selected_id, "Done")
                    st.success("Marked done.")
                    st.rerun()

            with a2:
                if st.button("Waiting"):
                    update_followup_status(selected_id, "Waiting")
                    st.success("Marked waiting.")
                    st.rerun()

            with a3:
                if st.button("Snooze +2 Days"):
                    snooze_followup(selected_id, 2)
                    st.success("Snoozed.")
                    st.rerun()

            with a4:
                if st.button("Snooze +7 Days"):
                    snooze_followup(selected_id, 7)
                    st.success("Snoozed.")
                    st.rerun()

            with a5:
                if st.button("Delete"):
                    delete_followup(selected_id)
                    st.success("Deleted.")
                    st.rerun()

        with tab_send:
            template_df = get_table("templates")
            template_body = ""

            if not template_df.empty:
                template_names = ["Blank"] + template_df["name"].tolist()
                template_choice = st.selectbox("Use template", template_names, key="follow_send_template")

                if template_choice != "Blank":
                    trow = template_df[template_df["name"] == template_choice].iloc[0]
                    template_body = trow["body"]

            with st.form("send_followup_mail"):
                to_email = st.text_input("To", value=row["from_email"])
                subject = st.text_input("Subject", value=f"Re: {row['subject']}" if not str(row["subject"]).lower().startswith("re:") else row["subject"])
                body = st.text_area("Message", value=template_body, height=260)

                send_follow_mail = st.form_submit_button("Send Mail")

            if send_follow_mail:
                try:
                    send_mail(
                        to_email=to_email,
                        subject=subject,
                        body=body,
                        sent_type="Follow-up",
                        related_followup_id=selected_id,
                    )
                    update_followup_status(selected_id, "Waiting")
                    st.success("Mail sent and follow-up marked Waiting.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Mail send nahi ho paya: {e}")

    st.markdown("---")

    st.download_button(
        "Download Follow-ups CSV",
        data=df_to_csv_bytes(follow_df),
        file_name="mail_followups.csv",
        mime="text/csv",
    )


# =========================================================
# PAGE: CONTACTS
# =========================================================

elif page == "Contacts":
    st.subheader("Contacts CRM")

    contacts_df = get_table("contacts")

    with st.expander("Add New Contact"):
        with st.form("new_contact"):
            name = st.text_input("Name")
            email_addr = st.text_input("Email")
            phone = st.text_input("Phone")
            company = st.text_input("Company")
            category = st.selectbox("Category", ["Customer", "Supplier", "Guest Post", "Agency", "Other"])
            tags = st.text_input("Tags")
            notes = st.text_area("Notes")

            add_contact_btn = st.form_submit_button("Add / Update Contact")

        if add_contact_btn:
            upsert_contact(name, email_addr, phone, company, category, notes, tags)
            st.success("Contact saved.")
            st.rerun()

    if contacts_df.empty:
        st.info("No contacts saved yet.")
    else:
        search_contact = st.text_input("Search contacts")

        filtered = contacts_df.copy()

        if search_contact.strip():
            k = search_contact.lower()
            filtered = filtered[
                filtered.apply(lambda r: k in " ".join([str(x).lower() for x in r.values]), axis=1)
            ]

        st.dataframe(filtered, use_container_width=True)

        st.download_button(
            "Download Contacts CSV",
            data=df_to_csv_bytes(contacts_df),
            file_name="mail_contacts.csv",
            mime="text/csv",
        )


# =========================================================
# PAGE: TEMPLATES
# =========================================================

elif page == "Templates":
    st.subheader("Email Templates")

    template_df = get_table("templates")

    with st.expander("Create New Template"):
        with st.form("template_form"):
            name = st.text_input("Template Name")
            category = st.text_input("Category", value="General")
            subject = st.text_input("Subject")
            body = st.text_area("Body", height=260)

            save_template = st.form_submit_button("Save Template")

        if save_template:
            if not name.strip() or not subject.strip() or not body.strip():
                st.warning("Name, subject, body required.")
            else:
                add_template(name, subject, body, category)
                st.success("Template saved.")
                st.rerun()

    if template_df.empty:
        st.info("No templates.")
    else:
        st.dataframe(template_df, use_container_width=True)

        options = [f"#{r['id']} | {r['name']}" for _, r in template_df.iterrows()]
        selected = st.selectbox("Delete template select karo", options)
        selected_id = int(selected.split("|")[0].replace("#", "").strip())

        if st.button("Delete Selected Template"):
            delete_template(selected_id)
            st.success("Template deleted.")
            st.rerun()


# =========================================================
# PAGE: SENT LOG
# =========================================================

elif page == "Sent Log":
    st.subheader("Sent Mail Log")

    sent_df = get_table("sent_log")

    if sent_df.empty:
        st.info("Abhi dashboard se koi mail sent nahi hua.")
    else:
        st.dataframe(sent_df.sort_values("sent_at", ascending=False), use_container_width=True)

        st.download_button(
            "Download Sent Log CSV",
            data=df_to_csv_bytes(sent_df),
            file_name="sent_mail_log.csv",
            mime="text/csv",
        )


# =========================================================
# PAGE: BACKUP
# =========================================================

elif page == "Backup":
    st.subheader("Backup & Safety")

    st.markdown(
        """
        <div class="card">
        Streamlit Cloud par SQLite file kabhi-kabhi redeploy/restart me reset ho sakti hai.
        Isliye regular backup download karna best hai.
        </div>
        """,
        unsafe_allow_html=True,
    )

    b1, b2, b3, b4 = st.columns(4)

    with b1:
        st.metric("Follow-ups", len(get_table("followups")))

    with b2:
        st.metric("Contacts", len(get_table("contacts")))

    with b3:
        st.metric("Templates", len(get_table("templates")))

    with b4:
        st.metric("Sent Logs", len(get_table("sent_log")))

    st.download_button(
        "Download Full Excel Backup",
        data=all_db_to_excel(),
        file_name="mail_crm_full_backup.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")

    st.warning("Backup import feature abhi add nahi kiya. Pehle download backup regularly rakho.")
