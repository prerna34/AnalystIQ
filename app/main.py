from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import sqlite3, csv, random, os, json, urllib.request, urllib.error, re
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "analyst.db"
app = FastAPI(title="Enterprise AI Business Analyst", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

class AskRequest(BaseModel):
    question: str


def create_data():
    DATA.mkdir(exist_ok=True)
    if DB.exists():
        return
    random.seed(23)
    banks = ["Northstar Bank", "Pioneer Bank", "Summit Bank", "Harbor Bank", "Crescent Bank"]
    merchants = [(f"M{i:04d}", f"Merchant {i:02d}", random.choice(["Retail", "Food", "Travel", "Digital", "Healthcare"])) for i in range(1, 31)]
    merchant_rows = [{"merchant_id": m[0], "merchant_name": m[1], "category": m[2], "country": random.choice(["IN", "US", "GB"])} for m in merchants]
    bank_rows = [{"bank_id": i+1, "bank_name": b, "region": random.choice(["North", "South", "East", "West"])} for i,b in enumerate(banks)]
    tx_rows = []
    start = datetime(2026, 1, 1)
    for i in range(1, 5001):
        dt = start + timedelta(minutes=random.randint(0, 180*24*60))
        m = random.choice(merchants); b = random.choice(banks)
        # Slightly different success rates to make segmentation meaningful.
        base = {"Northstar Bank": .965, "Pioneer Bank": .935, "Summit Bank": .952, "Harbor Bank": .905, "Crescent Bank": .948}[b]
        status = "SUCCESS" if random.random() < base else random.choice(["FAILED", "DECLINED"])
        tx_rows.append({"transaction_id": f"TX{i:06d}", "transaction_date": dt.strftime("%Y-%m-%d %H:%M:%S"), "merchant_id": m[0], "bank_id": banks.index(b)+1, "amount": round(random.uniform(100, 25000),2), "currency": "INR", "status": status, "channel": random.choice(["UPI", "CARD", "NETBANKING"]), "is_refund": 0})
    # Deliberately add 10 exact duplicate rows so the data-quality exception is demonstrable.
    tx_rows.extend([dict(tx_rows[i]) for i in range(9,19)])
    with open(DATA/"transactions.csv", "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=list(tx_rows[0])); w.writeheader(); w.writerows(tx_rows)
    with open(DATA/"merchants.csv", "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=list(merchant_rows[0])); w.writeheader(); w.writerows(merchant_rows)
    with open(DATA/"banks.csv", "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=list(bank_rows[0])); w.writeheader(); w.writerows(bank_rows)
    con=sqlite3.connect(DB)
    con.executescript('''
      CREATE TABLE transactions(transaction_id TEXT, transaction_date TEXT, merchant_id TEXT, bank_id INTEGER, amount REAL, currency TEXT, status TEXT, channel TEXT, is_refund INTEGER);
      CREATE TABLE merchants(merchant_id TEXT PRIMARY KEY, merchant_name TEXT, category TEXT, country TEXT);
      CREATE TABLE banks(bank_id INTEGER PRIMARY KEY, bank_name TEXT, region TEXT);
    ''')
    con.executemany("INSERT INTO transactions VALUES(:transaction_id,:transaction_date,:merchant_id,:bank_id,:amount,:currency,:status,:channel,:is_refund)", tx_rows)
    con.executemany("INSERT INTO merchants VALUES(:merchant_id,:merchant_name,:category,:country)", merchant_rows)
    con.executemany("INSERT INTO banks VALUES(:bank_id,:bank_name,:region)", bank_rows)
    con.commit(); con.close()

create_data()

SCHEMA = "transactions(transaction_id, transaction_date, merchant_id, bank_id, amount, currency, status, channel, is_refund); merchants(merchant_id, merchant_name, category, country); banks(bank_id, bank_name, region)"

def llm_sql(question: str):
    key=os.getenv("OPENAI_API_KEY", "").strip()
    if not key: return None
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt=f"Return only one SQLite SELECT query, no markdown. Schema: {SCHEMA}. User question: {question}. Use joins on transactions.merchant_id=merchants.merchant_id and transactions.bank_id=banks.bank_id. Success rate means 100.0*SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)/COUNT(*). Include meaningful group-by segmentation."
    payload={"model":model,"messages":[{"role":"system","content":"You are a careful payment analytics SQL generator. Use only the supplied schema. Output SQL only."},{"role":"user","content":prompt}],"temperature":0}
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r: out=json.loads(r.read().decode())
        sql=out["choices"][0]["message"]["content"].strip()
        return re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.I).strip()
    except Exception:
        return None

def rule_sql(q: str):
    s=q.lower()
    if any(x in s for x in ["success rate", "approval rate", "successful rate"]):
        if "bank" in s:
            return "SELECT b.bank_name AS segment, COUNT(*) AS transaction_count, ROUND(100.0*SUM(CASE WHEN t.status='SUCCESS' THEN 1 ELSE 0 END)/COUNT(*),2) AS success_rate_pct, ROUND(SUM(t.amount),2) AS total_amount FROM transactions t JOIN banks b ON t.bank_id=b.bank_id GROUP BY b.bank_name ORDER BY success_rate_pct DESC"
        if "channel" in s:
            return "SELECT channel AS segment, COUNT(*) AS transaction_count, ROUND(100.0*SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)/COUNT(*),2) AS success_rate_pct, ROUND(SUM(amount),2) AS total_amount FROM transactions GROUP BY channel ORDER BY success_rate_pct DESC"
        if "merchant" in s or "category" in s:
            return "SELECT m.merchant_name AS segment, m.category, COUNT(*) AS transaction_count, ROUND(100.0*SUM(CASE WHEN t.status='SUCCESS' THEN 1 ELSE 0 END)/COUNT(*),2) AS success_rate_pct FROM transactions t JOIN merchants m ON t.merchant_id=m.merchant_id GROUP BY m.merchant_id ORDER BY success_rate_pct DESC LIMIT 15"
        return "SELECT status AS segment, COUNT(*) AS transaction_count, ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM transactions),2) AS share_pct FROM transactions GROUP BY status ORDER BY transaction_count DESC"
    if any(x in s for x in ["volume", "monthly", "month", "trend", "over time"]):
        return "SELECT substr(transaction_date,1,7) AS segment, COUNT(*) AS transaction_count, ROUND(SUM(amount),2) AS total_amount FROM transactions GROUP BY substr(transaction_date,1,7) ORDER BY segment"
    if "top merchant" in s or "highest merchant" in s or "merchant by amount" in s or ("merchant" in s and "amount" in s):
        return "SELECT m.merchant_name AS segment, m.category, COUNT(*) AS transaction_count, ROUND(SUM(t.amount),2) AS total_amount FROM transactions t JOIN merchants m ON t.merchant_id=m.merchant_id GROUP BY m.merchant_id ORDER BY total_amount DESC LIMIT 10"
    if "failed" in s or "failure" in s or "declined" in s:
        return "SELECT status AS segment, channel, COUNT(*) AS transaction_count, ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM transactions),2) AS share_pct FROM transactions WHERE status!='SUCCESS' GROUP BY status, channel ORDER BY transaction_count DESC"
    if "channel" in s:
        return "SELECT channel AS segment, COUNT(*) AS transaction_count, ROUND(100.0*SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)/COUNT(*),2) AS success_rate_pct, ROUND(SUM(amount),2) AS total_amount FROM transactions GROUP BY channel ORDER BY transaction_count DESC"
    if "category" in s:
        return "SELECT m.category AS segment, COUNT(*) AS transaction_count, ROUND(SUM(t.amount),2) AS total_amount, ROUND(100.0*SUM(CASE WHEN t.status='SUCCESS' THEN 1 ELSE 0 END)/COUNT(*),2) AS success_rate_pct FROM transactions t JOIN merchants m ON t.merchant_id=m.merchant_id GROUP BY m.category ORDER BY total_amount DESC"
    return "SELECT status AS segment, COUNT(*) AS transaction_count, ROUND(SUM(amount),2) AS total_amount FROM transactions GROUP BY status ORDER BY transaction_count DESC"


def validate_sql(sql: str):
    clean=sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^select\b", clean): raise ValueError("Only SELECT queries are allowed.")
    if ";" in clean: raise ValueError("Multiple SQL statements are not allowed.")
    forbidden=r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|into|load_extension)\b"
    if re.search(forbidden, clean, re.I): raise ValueError("Unsafe SQL keyword detected.")
    allowed={"transactions","merchants","banks"}
    tables=re.findall(r"(?i)\b(?:from|join)\s+([a-z_][a-z0-9_]*)", clean)
    if not tables or any(t.lower() not in allowed for t in tables): raise ValueError("Query references a table outside the approved dataset.")
    return clean


def execute_readonly(sql):
    con=sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory=sqlite3.Row
    def authorizer(action, arg1, arg2, db, trigger):
        allowed={sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
    con.set_authorizer(authorizer)
    try:
        cur=con.execute(sql)
        rows=[dict(r) for r in cur.fetchmany(250)]
        cols=[d[0] for d in cur.description or []]
        return cols, rows
    finally: con.close()


def quality_report():
    con=sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    total=con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    duplicates=con.execute("SELECT COUNT(*) FROM (SELECT transaction_id FROM transactions GROUP BY transaction_id HAVING COUNT(*)>1)").fetchall()
    dup_rows=con.execute("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM transactions GROUP BY transaction_id HAVING c>1)").fetchone()[0]
    missing=con.execute("SELECT COUNT(*) FROM transactions WHERE transaction_id IS NULL OR amount IS NULL OR status IS NULL").fetchone()[0]
    con.close()
    return {"rows":total,"duplicate_transaction_ids":len(duplicates),"duplicate_extra_rows":dup_rows,"missing_critical_fields":missing,"status":"warning" if dup_rows or missing else "passed"}

@app.get("/")
def home(): return FileResponse(ROOT/"static"/"index.html")
@app.get("/api/health")
def health(): return {"status":"ok","database":"SQLite","llm_enabled":bool(os.getenv("OPENAI_API_KEY")),"quality":quality_report()}
@app.get("/api/datasets")
def datasets():
    return {"datasets":[{"name":"transactions","rows":5010,"description":"Payment transaction events; includes a deliberately injected duplicate sample for quality checks."},{"name":"merchants","rows":30,"description":"Merchant profile and category."},{"name":"banks","rows":5,"description":"Acquiring bank profile."}],"schema":SCHEMA}
@app.get("/api/quality")
def quality(): return quality_report()
@app.post("/api/ask")
def ask(req: AskRequest):
    q=req.question.strip()
    if len(q)<4: raise HTTPException(400,"Please enter a more specific business question.")
    generated=llm_sql(q)
    sql=generated or rule_sql(q)
    source="LLM-generated SQL" if generated else "Local SQL planner"
    try:
        sql=validate_sql(sql)
        cols,rows=execute_readonly(sql)
    except Exception as e:
        # If the optional model produced invalid SQL, safely retry using local planner.
        fallback=validate_sql(rule_sql(q))
        try: cols,rows=execute_readonly(fallback); sql=fallback; source="Local SQL planner (safe fallback)"
        except Exception as e2: raise HTTPException(422,f"Query could not be safely executed: {e2}")
    quality=quality_report()
    evidence={"dataset":"transactions + dimensions where joined","sql":sql,"row_limit":250,"returned_rows":len(rows),"filters":"No user-specified date filter was applied.","quality_note":f"{quality['duplicate_extra_rows']} duplicate extra transaction rows are present; aggregate counts may be inflated." if quality['duplicate_extra_rows'] else "No duplicate transaction IDs detected."}
    return {"question":q,"sql":sql,"sql_source":source,"columns":cols,"rows":rows,"evidence":evidence,"quality":quality,"caveats":["This is synthetic demonstration data, not real payment-provider data.","No date range was inferred; the query uses all available records unless SQL says otherwise.","Duplicate transaction IDs are flagged and not silently removed."]}
@app.post("/api/demo/failure")
def failure_demo():
    bad="DELETE FROM transactions"
    try: validate_sql(bad)
    except Exception as e: return {"check":"Unsafe SQL rejected","passed":True,"message":str(e),"recovery":"The app does not execute the statement and keeps the dataset unchanged."}
    return {"check":"Unsafe SQL rejected","passed":False,"message":"Unexpected validation result"}
