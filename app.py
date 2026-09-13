"""
AskMySales — conversational analytics on Exasol.

Run:
    streamlit run app.py
"""
import os
import re
import ssl

import pandas as pd
import plotly.express as px
import pyexasol
import streamlit as st
from google import genai
from dotenv import load_dotenv

load_dotenv()

EXASOL_HOST = os.environ["EXASOL_HOST"]
EXASOL_PORT = os.environ["EXASOL_PORT"]
EXASOL_USER = os.environ["EXASOL_USER"]
EXASOL_PASSWORD = os.environ["EXASOL_PASSWORD"]
EXASOL_SCHEMA = os.environ.get("EXASOL_SCHEMA", "RETAIL")
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = "gemini-3.6-flash"
MAX_ROWS = 500

st.set_page_config(page_title="AskMySales", page_icon="📊", layout="wide")


# ---------- Exasol ----------

@st.cache_resource
def get_connection():
    dsn = f"{EXASOL_HOST}:{EXASOL_PORT}"
    return pyexasol.connect(
        dsn=dsn,
        user=EXASOL_USER,
        password=EXASOL_PASSWORD,
        compression=True,
        websocket_sslopt={"cert_reqs": ssl.CERT_NONE},
    )


@st.cache_data(ttl=600)
def get_schema_description() -> str:
    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT COLUMN_NAME, COLUMN_TYPE
        FROM EXA_ALL_COLUMNS
        WHERE COLUMN_SCHEMA = '{EXASOL_SCHEMA}' AND COLUMN_TABLE = 'SALES'
        ORDER BY COLUMN_ORDINAL_POSITION
        """
    ).fetchall()
    cols = "\n".join(f"  - {name}: {ctype}" for name, ctype in rows)
    return f"Table {EXASOL_SCHEMA}.SALES columns:\n{cols}"


def run_query(sql: str) -> pd.DataFrame:
    conn = get_connection()
    return conn.export_to_pandas(sql)


# ---------- LLM: natural language -> SQL ----------

client = genai.Client(api_key=GEMINI_API_KEY)

SQL_SYSTEM_PROMPT = """You are a SQL generator for the Exasol database. \
Given a table schema and a business question, output ONE single read-only \
SELECT statement that answers it. Rules:
- Output ONLY the SQL. No explanation, no markdown fences.
- Only SELECT statements. Never write/alter/delete data.
- Always include an explicit LIMIT (max {max_rows}) unless the query already \
aggregates down to a small number of rows.
- Use standard Exasol SQL syntax.
"""


def question_to_sql(question: str, schema_text: str) -> str:
    prompt = (
        f"{SQL_SYSTEM_PROMPT.format(max_rows=MAX_ROWS)}\n\n"
        f"{schema_text}\n\nQuestion: {question}\n\nSQL:"
    )
    response = client.models.generate_content(model=MODEL, contents=prompt)
    sql = response.text.strip()
    sql = re.sub(r"^```sql\s*|\s*```$", "", sql, flags=re.IGNORECASE).strip()
    return sql


def is_safe_select(sql: str) -> bool:
    stripped = sql.strip().strip(";").strip()
    if not re.match(r"(?is)^select\b", stripped):
        return False
    forbidden = r"\b(insert|update|delete|drop|alter|truncate|merge|create|grant|revoke)\b"
    return re.search(forbidden, stripped, flags=re.IGNORECASE) is None


# ---------- Anomaly flagging ----------

def find_anomalies(df: pd.DataFrame) -> list[str]:
    notes = []
    numeric_cols = df.select_dtypes(include="number").columns
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 5 or series.std() == 0:
            continue
        z = (series - series.mean()) / series.std()
        outliers = df.loc[z[abs(z) > 2].index]
        if not outliers.empty:
            notes.append(
                f"Found {len(outliers)} unusual value(s) in **{col}** "
                f"(more than 2 standard deviations from the mean)."
            )
    return notes


# ---------- Auto-chart ----------

def auto_chart(df: pd.DataFrame):
    if df.shape[0] < 2 or df.shape[1] < 2:
        return None
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    non_numeric_cols = [c for c in df.columns if c not in numeric_cols]
    if not numeric_cols or not non_numeric_cols:
        return None

    x_col = non_numeric_cols[0]
    y_col = numeric_cols[0]

    if df[x_col].nunique() > 40:
        return px.line(df, x=x_col, y=y_col, title=f"{y_col} over {x_col}")
    return px.bar(df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")


# ---------- UI ----------

st.title("📊 AskMySales")
st.caption("Ask questions about retail sales in plain English — answered live from Exasol.")

with st.sidebar:
    st.subheader("About")
    st.write(
        "This app translates natural-language questions into SQL, runs them "
        "directly against **Exasol Personal**, and surfaces anomalies "
        "automatically — built for the Exasol AI + Data Challenge."
    )
    st.subheader("Try asking")
    st.write(
        "- Which region had the highest sales last month?\n"
        "- Show me daily revenue for the East region\n"
        "- Which product category has the most refunds?\n"
        "- Are there any unusual orders recently?"
    )

if "history" not in st.session_state:
    st.session_state.history = []

question = st.chat_input("Ask a question about your sales data...")

for entry in st.session_state.history:
    with st.chat_message(entry["role"]):
        st.markdown(entry["content"])
        if entry.get("df") is not None:
            st.dataframe(entry["df"], use_container_width=True)
        if entry.get("chart") is not None:
            st.plotly_chart(entry["chart"], use_container_width=True)

if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking in SQL..."):
            try:
                schema_text = get_schema_description()
                sql = question_to_sql(question, schema_text)

                if not is_safe_select(sql):
                    st.error("I generated a query I'm not comfortable running. Try rephrasing.")
                    st.session_state.history.append(
                        {"role": "assistant", "content": "Could not safely answer that question.", "df": None, "chart": None}
                    )
                else:
                    with st.expander("Generated SQL"):
                        st.code(sql, language="sql")

                    df = run_query(sql)
                    st.dataframe(df, use_container_width=True)

                    chart = auto_chart(df)
                    if chart is not None:
                        st.plotly_chart(chart, use_container_width=True)

                    anomaly_notes = find_anomalies(df)
                    reply_text = "Here's what I found."
                    if anomaly_notes:
                        reply_text += "\n\n⚠️ **Heads up:**\n" + "\n".join(f"- {n}" for n in anomaly_notes)
                    st.markdown(reply_text)

                    st.session_state.history.append(
                        {"role": "assistant", "content": reply_text, "df": df, "chart": chart}
                    )
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                st.session_state.history.append(
                    {"role": "assistant", "content": f"Error: {e}", "df": None, "chart": None}
                )
